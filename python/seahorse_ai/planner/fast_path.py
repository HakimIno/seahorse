"""Enhanced Fast Path Router for immediate fulfillment of common requests.

This module acts as a lightweight dispatcher that delegates specialized analysis
to dedicated handlers, reducing latency and complexity for specific domains.

Optimizations:
- Simple task detection (SQL, chart, basic queries)
- Token budgeting to prevent runaway LLM calls
- Schema caching to avoid repeated dumps
- Direct execution paths for common patterns
"""

from __future__ import annotations

import logging
import re
import time
from typing import TYPE_CHECKING

from msgspec import Struct

from seahorse_ai.core.schemas import AgentResponse, Message
from seahorse_ai.planner.fast_utils import robust_json_load
from seahorse_ai.planner.handlers.entity import EntityHandler
from seahorse_ai.planner.handlers.polars import PolarsHandler
from seahorse_ai.planner.handlers.story import StoryHandler

if TYPE_CHECKING:
    from seahorse_ai.core.router import ModelRouter
    from seahorse_ai.tools.base import ToolRegistry

logger = logging.getLogger(__name__)


class StructuredIntent(Struct, omit_defaults=True):
    """Result of the intent classification step."""

    intent: str
    action: str = "CHAT"
    entity: str | None = None
    timeframe: str | None = None
    complexity: int = 1
    tone: str = "professional"
    raw_category: str | None = None


_CLASSIFY_SYSTEM_PROMPT = """\
You are an intelligent request analyzer for Seahorse AI. REASON about what the user needs, then classify.

## Think Step-by-Step

1. **Greeting or social?** → GENERAL, complexity=1
2. **Needs CURRENT or REAL-TIME data?** Ask: "Could this answer have changed in the last year?" If yes → PUBLIC_REALTIME
3. **Refers to PRIVATE/INTERNAL data?** (stored products, past conversations, packages) → PRIVATE_MEMORY
4. **Needs CORPORATE DATABASE?** (sales, orders, customers, business metrics) → DATABASE
5. **Complex multi-step analysis or deep research?** (comparisons, forecasts, reports) → STORY
6. **Simple data lookup or chart from files?** → POLARS
7. **Everything else** (timeless knowledge, coding, math, creative writing) → GENERAL

## Key Principle
Your training data has a cutoff. ANY factual question where the real-world answer MIGHT have changed → PUBLIC_REALTIME. When in doubt, prefer PUBLIC_REALTIME over GENERAL.

## Complexity: 1=no tools, 2=one tool, 3=2-3 tools, 4=multi-step, 5=deep research

Return ONLY valid JSON: {"intent":"...","action":"...","entity":"...or null","complexity":1-5,"tone":"professional|casual"}
"""


async def classify_structured_intent(
    prompt: str, llm: ModelRouter, history: list[Message] | None = None
) -> StructuredIntent:
    """Classify the user's intent into a structured format for routing.
    
    ULTRA-FAST PATH: Uses regex for greetings and simple acknowledgments (0ms LLM cost).
    """
    p = prompt.strip().lower()
    
    # 1. Ultra-Fast Regex Patterns (Greetings & Acknowledgments)
    greetings = r"^(hi|hello|hey|สวัสดี|หวัดดี|ดีครับ|ดีค่ะ|ฮัลโหล|sup|yo|hola)$"
    thanks = r"^(thanks|thank you|ขอบคุณ|แต๊งกิ้ว|ขอบใจ|ok|okay|โอเค|ตกลง|affirmative|yes|no|ใช่|ไม่ใช่)$"
    identity = r"^(who are you|คุณคือใคร|what is your name|ทำอะไรได้บ้าง|help|ช่วยเหลือ)$"
    
    if re.match(greetings, p):
        return StructuredIntent(intent="GENERAL", action="CHAT", complexity=1, tone="casual")
    if re.match(thanks, p):
        return StructuredIntent(intent="GENERAL", action="CHAT", complexity=1, tone="professional")
    if re.match(identity, p):
        return StructuredIntent(intent="GENERAL", action="CHAT", complexity=1, tone="professional")

    # 2. Standard Fast Path (LLM-based)
    msgs = [Message(role="system", content=_CLASSIFY_SYSTEM_PROMPT)]
    if history:
        msgs.extend(history[-2:])
    msgs.append(Message(role="user", content=prompt))

    res = await llm.complete(msgs, tier="fast")
    data = robust_json_load(str(res.get("content", res) if isinstance(res, dict) else res))

    return StructuredIntent(
        intent=data.get("intent", "GENERAL"),
        action=data.get("action", "CHAT"),
        entity=data.get("entity"),
        complexity=int(data.get("complexity", 1)),
        tone=data.get("tone", "professional"),
        raw_category=data.get("intent"),
    )


class FastPathRouter:
    """Intelligently routes requests to specialized high-speed handlers."""

    def __init__(self, tools: ToolRegistry, llm_backend: ModelRouter):
        # Swap args to match ReActPlanner's __init__ order
        self._llm = llm_backend
        self._tools = tools

        # Initialize handlers
        self._polars = PolarsHandler(llm_backend, tools)
        self._story = StoryHandler(llm_backend, tools)
        self._entity = EntityHandler(llm_backend, tools)

    async def try_route(
        self, si: StructuredIntent, agent_id: str, prompt: str, history: list[Message] | None = None
    ) -> AgentResponse | None:
        """Backward-compatible entry point for ReActPlanner.

        Routes to fast handlers for simple intents. Complex intents
        (DATABASE, PUBLIC_REALTIME, PRIVATE_MEMORY) fall through to
        the full ReAct loop for proper multi-step handling.
        """
        start_t = time.perf_counter()
        intent = si.intent.upper()

        if intent == "STORY":
            return await self._story.handle(prompt, history, start_t)
        elif intent == "POLARS":
            return await self._polars.handle(prompt, history, start_t)
        elif intent == "DIRECT":
            return await self._entity.handle(prompt, history, start_t, intent="direct")

        # DATABASE, PUBLIC_REALTIME, PRIVATE_MEMORY, GENERAL → full ReAct loop
        return None

    async def query(
        self, prompt: str, history: list[Message] | None = None
    ) -> AgentResponse | None:
        """Alternative direct entry point."""
        si = await classify_structured_intent(prompt, self._llm, history)
        return await self.try_route(si, "default", prompt, history)
