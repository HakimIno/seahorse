"""Enhanced Fast Path Router for immediate fulfillment of common requests.

This module acts as a lightweight dispatcher that delegates specialized analysis
to dedicated handlers, reducing latency and complexity for specific domains.
"""

from __future__ import annotations

import logging
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


async def classify_structured_intent(
    prompt: str, llm: ModelRouter, history: list[Message] | None = None
) -> StructuredIntent:
    """Classify the user's intent into a structured format for routing."""
    # Use a fast classification prompt
    sys = (
        "Classify user intent. Categories: STORY (complex, professional analysis + narrative), "
        "POLARS (simple data/trends/charts), "
        "INTERNAL (codebase), DIRECT (simple facts), GENERAL (chat).\n"
        'Return JSON: { "intent": "...", "action": "...", "complexity": 1-5 }'
    )
    msgs = [Message(role="system", content=sys)]
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
        """Backward-compatible entry point for ReActPlanner."""
        start_t = time.perf_counter()
        intent = si.intent.upper()

        if intent == "STORY":
            return await self._story.handle(prompt, history, start_t)
        elif intent == "POLARS":
            return await self._polars.handle(prompt, history, start_t)
        elif intent == "INTERNAL":
            return await self._entity.handle(prompt, history, start_t, intent="internal")
        elif intent == "DIRECT":
            return await self._entity.handle(prompt, history, start_t, intent="direct")

        return None

    async def query(
        self, prompt: str, history: list[Message] | None = None
    ) -> AgentResponse | None:
        """Alternative direct entry point."""
        si = await classify_structured_intent(prompt, self._llm, history)
        return await self.try_route(si, "default", prompt, history)
