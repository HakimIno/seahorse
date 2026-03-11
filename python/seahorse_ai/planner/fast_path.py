"""seahorse_ai.planner.fast_path — Structured Intent Router.

Replaces the keyword hard-code approach with a single LLM call that returns
structured JSON: {intent, action, entity, needs_clarification}.

For simple actions (STORE, QUERY, GREET), the Fast Path executes the tool
directly without entering the ReAct loop — reducing latency from ~12s to ~3s.

Phase 2 upgrade: _handle_store uses LLM MemoryExtractor (no regex splitting).
Falls back to regex if extractor unavailable.

Complex actions (SEARCH_WEB, SQL, CHAT, CLARIFY) fall through to ReAct.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from seahorse_ai.schemas import AgentResponse, Message

logger = logging.getLogger(__name__)


@dataclass
class StructuredIntent:
    """Result of structured intent classification."""

    intent: str = "GENERAL"  # GENERAL|PUBLIC_REALTIME|PRIVATE_MEMORY|DATABASE
    action: str = "CHAT"  # STORE|QUERY|UPDATE|DELETE|SEARCH_WEB|SQL|GREET|CHAT|CLARIFY
    entity: str | None = None  # The key data to store/search
    needs_clarification: bool = False  # True if ambiguous
    complexity: int = 3  # 1-5 (1: Easy/Greetings, 5: Multi-agent project)
    tone: str = "PROFESSIONAL"  # PROFESSIONAL | CASUAL
    raw_category: str = ""  # Legacy category for compatibility


# Actions that bypass ReAct tools but still generate natural responses
_FAST_ACTIONS = frozenset({"STORE", "QUERY", "GREET", "CHAT"})

# (Removed hardcoded _GREETINGS and _CHAT_FALLBACKS arrays)

STRUCTURED_INTENT_PROMPT = """\
Analyze the user query and return ONLY valid JSON (no markdown, no explanation).

Fields:
- "intent": one of GENERAL, PUBLIC_REALTIME, PRIVATE_MEMORY, DATABASE
- "action": one of STORE, QUERY, UPDATE, DELETE, SEARCH_WEB, SQL, GREET, CHAT, CLARIFY
- "entity": the key data to store/search/update (string or null)
- "needs_clarification": true if the request is ambiguous
- "complexity": 1-5 (Integer)
- "tone": "PROFESSIONAL" (for work, facts, data) or "CASUAL" (for jokes, greetings, small talk)
    - 1-2: Simple facts, greetings, or basic storage.
    - 3: Complex tool usage, analysis, or logic (Single Agent).
    - 4-5: Multi-step objectives, deep research, or projects (Specialized Crew required).

Rules:
- Simple greetings/casual talk → {{"action":"GREET","complexity":1}}
- "Save/Remember X" → {{"action":"STORE","complexity":2}}
- "What is X" (simple facts) → {{"action":"QUERY","complexity":2}}
- Database/SQL queries → {{"action":"SQL","complexity":3}}
- "Research X", "Summarize X", "Write a report about X", "Explain complex Y" 
  → **STRICTLY** {{"action":"CHAT","complexity":4}} or 5.
- Multi-step requests or deep analysis → {{"complexity":5}}


Conversation history (if any):
{history_summary}

User query: "{query}"
"""


async def classify_structured_intent(
    query: str,
    llm_backend: object,
    history: list[Message] | None = None,
) -> StructuredIntent:
    """Classify intent with structured output in 1 LLM call.

    Returns a StructuredIntent with action, entity, and clarification flag.
    Falls back to GENERAL/CHAT on any error.
    """
    from seahorse_ai.prompts.intent import _is_greeting

    q_lower = query.lower().strip()

    # Tier 0: Greeting fast-path (0 LLM calls for classification)
    if _is_greeting(q_lower):
        return StructuredIntent(
            intent="GENERAL",
            action="GREET",
            raw_category="GENERAL",
        )

    # Tier 1: Single LLM call for structured classification
    history_summary = ""
    if history:
        recent = [m for m in history[-6:] if m.role in ("user", "assistant") and m.content]
        if recent:
            history_summary = "\n".join(f"- {m.role}: {(m.content or '')[:100]}" for m in recent)

    prompt = STRUCTURED_INTENT_PROMPT.format(
        query=query,
        history_summary=history_summary or "(no history)",
    )

    try:
        result = await llm_backend.complete(  # type: ignore[union-attr]
            [Message(role="user", content=prompt)], tier="fast"
        )
        logger.info("structured_intent raw result: %r", result)

        # Handle both dict and string results
        if isinstance(result, dict):
            data = result.get("content", result)
            if isinstance(data, str):
                data = _robust_json_load(data)
        else:
            data = _robust_json_load(str(result))

        si = StructuredIntent(
            intent=data.get("intent", "GENERAL").upper(),
            action=data.get("action", "CHAT").upper(),
            entity=data.get("entity"),
            needs_clarification=data.get("needs_clarification", False),
            complexity=int(data.get("complexity", 3)),
            tone=data.get("tone", "PROFESSIONAL").upper(),
        )
        # Set legacy category
        si.raw_category = si.intent
        logger.info(
            "structured_intent: intent=%s action=%s entity=%r clarify=%s",
            si.intent,
            si.action,
            si.entity,
            si.needs_clarification,
        )
        return si

    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.warning("structured_intent parse error: %s", exc)
        # Fallback: use keyword-based classification
        from seahorse_ai.prompts.intent import (
            MEMORY_KEYWORDS,
            REALTIME_KEYWORDS,
        )

        for kw in MEMORY_KEYWORDS:
            if kw.lower() in q_lower:
                return StructuredIntent(
                    intent="PRIVATE_MEMORY",
                    action="QUERY",
                    raw_category="PRIVATE_MEMORY",
                )
        for kw in REALTIME_KEYWORDS:
            if kw.lower() in q_lower:
                return StructuredIntent(
                    intent="PUBLIC_REALTIME",
                    action="SEARCH_WEB",
                    raw_category="PUBLIC_REALTIME",
                )
        # Default to CHAT (slow path) for everything else, including mocks
        return StructuredIntent(intent="GENERAL", action="CHAT", raw_category="GENERAL")

    except Exception as exc:  # noqa: BLE001
        logger.error("structured_intent failed: %s", exc)
        return StructuredIntent(intent="GENERAL", action="CHAT", raw_category="GENERAL")


class FastPathRouter:
    """Execute simple actions directly — bypass the ReAct loop.

    Handles STORE, QUERY, GREET, and CHAT without the slow ReAct executor overhead.
    Complex actions (SEARCH_WEB, SQL, CLARIFY, UPDATE) fall through.
    """

    def __init__(self, tools: object, llm_backend: object = None) -> None:
        self._tools = tools
        self._llm = llm_backend

    async def try_route(
        self,
        si: StructuredIntent,
        agent_id: str,
        prompt: str,
        history: list[Message] | None = None,
    ) -> AgentResponse | None:
        """Try to handle via fast path. Returns None if ReAct loop needed."""
        if si.needs_clarification:
            return None  # Let ReAct + LLM ask clarifying question

        if si.action not in _FAST_ACTIONS:
            return None  # Complex → ReAct loop

        import time

        start_t = time.perf_counter()

        if si.action == "GREET":
            return await self._handle_conversational(prompt, history, start_t, tone=si.tone)

        if si.action == "CHAT":
            if si.complexity <= 2:
                return await self._handle_conversational(prompt, history, start_t, tone=si.tone)
            return None  # Complexity 3+ → ReAct or Auto-Seahorse

        if si.action == "STORE" and si.entity:
            return await self._handle_store(si.entity, agent_id)

        if si.action == "QUERY" and si.entity:
            return await self._handle_query(si.entity, agent_id, history)

        return None

    async def _handle_conversational(
        self, prompt: str, history: list[Message] | None, start_t: float, tone: str = "PROFESSIONAL"
    ) -> AgentResponse:
        """Process greetings and simple chat queries fully via the fast model."""
        import time

        from seahorse_ai.schemas import Message

        # Select persona based on tone
        if tone == "CASUAL":
            system_msg = (
                "You are Seahorse AI, but in a friendly, casual, and slightly humorous mode. "
                "You are chatting with a friend. Use emojis, be warm, and keep it light. "
                "Reply in the user's language."
            )
        else:
            system_msg = (
                "You are Seahorse AI, an intelligent business agent. "
                "You are professional, precise, and helpful. "
                "Answer politely, concisely, and naturally in the user's language."
            )

        msgs = [Message(role="system", content=system_msg)]
        if history:
            # OPTIMIZATION: Truncate history for greetings.
            # Usually only need last 2 turns to maintain flow without token waste.
            msgs.extend(history[-2:])
        msgs.append(Message(role="user", content=prompt))

        try:
            # Use the 'fast' tier (gemini-3.1-flash-lite) for extreme efficiency
            res = await self._llm.complete(msgs, tier="fast")
            content = str(res.get("content", res) if isinstance(res, dict) else res)
        except Exception as e:
            logger.error(f"Fast chat fallback error: {e}")
            content = "Sorry, I encountered an issue processing that."

        return AgentResponse(
            content=content,
            steps=1,
            elapsed_ms=int((time.perf_counter() - start_t) * 1000),
        )

    async def _handle_store(
        self,
        entity: str,
        agent_id: str,
    ) -> AgentResponse:
        """Store entity in memory.

        Phase 2: Uses LLM MemoryExtractor to split + type + score facts.
        Falls back to regex splitting if extractor unavailable.
        """
        try:
            # Phase 2: LLM-based extraction (preferred — no hard-code)
            facts = await self._extract_facts(entity)
            stored: list[str] = []

            for fact in facts:
                await self._tools.call(  # type: ignore[union-attr]
                    "memory_store",
                    {
                        "text": fact.text,
                        "agent_id": agent_id,
                        "importance": fact.importance,
                    },
                )
                stored.append(fact.text)
                logger.info(
                    "fast_path.store: type=%s importance=%d text=%r",
                    fact.fact_type,
                    fact.importance,
                    fact.text,
                )

            if len(stored) == 1:
                content = f"บันทึกเรียบร้อยครับ: {stored[0]} ✅"
            else:
                lines = "\n".join(f"  • {s}" for s in stored)
                content = f"บันทึกเรียบร้อย {len(stored)} รายการ ✅\n{lines}"

            return AgentResponse(
                content=content,
                steps=0,
                agent_id=agent_id,
                elapsed_ms=0,
            )
        except Exception as exc:
            logger.error("fast_path.store failed: %s", exc)
            return None  # type: ignore[return-value]

    async def _extract_facts(self, text: str) -> list[object]:
        """Extract MemoryFacts via LLM extractor, falling back to regex."""
        try:
            from seahorse_ai.tools.memory_extractor import MemoryExtractor

            extractor = MemoryExtractor(llm_backend=self._llm)
            return await extractor.extract(text)
        except Exception as exc:
            logger.warning("fast_path: MemoryExtractor unavailable (%s) — using regex split", exc)
            from seahorse_ai.tools.memory_extractor import MemoryFact

            items = _split_entities(text)
            return [MemoryFact(text=item, importance=3) for item in items]

    async def _handle_query(
        self, entity: str, agent_id: str, history: list[Message] | None = None
    ) -> AgentResponse | None:
        """Search memory and synthesize an answer (Phase 4)."""
        try:
            from seahorse_ai.planner.memory_reasoner import MemoryReasoner

            reasoner = MemoryReasoner(llm_backend=self._llm, tools_registry=self._tools)
            return await reasoner.reason(query=entity, agent_id=agent_id, history=history)
        except Exception as exc:
            logger.error("fast_path.query failed: %s", exc)
            return None


# ── Helper functions ───────────────────────────────────────────────────────────

import re  # noqa: E402

_SPLIT_DELIMITERS = re.compile(r"[,،;]\s*|\sและ\s|\sand\s", re.IGNORECASE)


def _split_entities(entity: str) -> list[str]:
    """Split comma/และ/and-separated items into individual facts.

    'Packet B ราคา 5,000 , Packet C ราคา 7,500'
    → ['Packet B ราคา 5,000', 'Packet C ราคา 7,500']

    Handles price commas (1,200) by only splitting on comma-space.
    """
    # Only split on ", " (comma + space) to avoid splitting "1,200"
    parts = re.split(r",\s+|\sและ\s|\sand\s", entity, flags=re.IGNORECASE)
    items = [p.strip() for p in parts if p.strip() and len(p.strip()) > 3]
    return items if items else [entity]


def _robust_json_load(text: str) -> dict[str, Any]:
    """Extract and parse JSON from text, handling markdown fences or preamble."""
    text = text.strip()
    # Find the first '{' and last '}'
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    return {}
