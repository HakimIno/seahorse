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

from seahorse_ai.schemas import AgentResponse, Message

logger = logging.getLogger(__name__)


@dataclass
class StructuredIntent:
    """Result of structured intent classification."""
    intent: str = "GENERAL"            # GENERAL|PUBLIC_REALTIME|PRIVATE_MEMORY|DATABASE
    action: str = "CHAT"               # STORE|QUERY|UPDATE|DELETE|SEARCH_WEB|SQL|GREET|CHAT|CLARIFY
    entity: str | None = None          # The key data to store/search
    needs_clarification: bool = False   # True if ambiguous
    raw_category: str = ""             # Legacy category for compatibility


# Actions that can bypass ReAct loop entirely
_FAST_ACTIONS = frozenset({"STORE", "QUERY", "GREET"})

# Greeting responses (no LLM needed)
_GREETINGS = [
    "สวัสดีครับ! มีอะไรให้ช่วยไหมครับ? 😊",
    "สวัสดีครับ! ผมพร้อมช่วยเหลือครับ",
]

# Simple chat responses (for testing or very basic interaction)
_CHAT_FALLBACKS = [
    "เข้าใจแล้วครับ มีอะไรให้ผมช่วยเพิ่มเติมไหม?",
    "รับทราบครับ ผมพร้อมช่วยหาข้อมูลหรือช่วยงานอื่นๆ นะครับ",
]


STRUCTURED_INTENT_PROMPT = """\
Analyze the user query and return ONLY valid JSON (no markdown, no explanation).

Fields:
- "intent": one of GENERAL, PUBLIC_REALTIME, PRIVATE_MEMORY, DATABASE
- "action": one of STORE, QUERY, UPDATE, DELETE, SEARCH_WEB, SQL, GREET, CHAT, CLARIFY
- "entity": the key data to store/search/update (string or null)
- "needs_clarification": true if the request is ambiguous

Rules:
- "จำไว้ว่า X" / "save X" / "remember X" → {{"intent":"PRIVATE_MEMORY","action":"STORE","entity":"X"}}
- "X ราคาเท่าไหร่" / "what is X price"
  → {{"intent":"PRIVATE_MEMORY","action":"QUERY","entity":"X price"}}
- "เปลี่ยนราคา X เป็น Y"
  → {{"intent":"PRIVATE_MEMORY","action":"UPDATE","entity":"X price Y"}}
- "เปลี่ยนเป็น Y" (no subject) → {{"action":"CLARIFY","needs_clarification":true}}
- "ราคาทองวันนี้" / "gold price" → {{"intent":"PUBLIC_REALTIME","action":"SEARCH_WEB","entity":"gold price today"}}
- "ข่าวล่าสุด" → {{"intent":"PUBLIC_REALTIME","action":"SEARCH_WEB","entity":"latest news"}}
- "Hi" / "สวัสดี" → {{"intent":"GENERAL","action":"GREET"}}
- General questions / coding → {{"intent":"GENERAL","action":"CHAT"}}
- Database queries / "เชื่อมต่อฐานข้อมูลอะไร" / "schema" → {{"intent":"DATABASE","action":"SQL","entity":"current connection status"}}

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

    # Tier 0: Greeting fast-path (0 LLM calls)
    if _is_greeting(q_lower):
        return StructuredIntent(
            intent="GENERAL", action="GREET",
            raw_category="GENERAL",
        )

    # Tier 1: Single LLM call for structured classification
    history_summary = ""
    if history:
        recent = [
            m for m in history[-6:]
            if m.role in ("user", "assistant") and m.content
        ]
        if recent:
            history_summary = "\n".join(
                f"- {m.role}: {(m.content or '')[:100]}" for m in recent
            )

    prompt = STRUCTURED_INTENT_PROMPT.format(
        query=query,
        history_summary=history_summary or "(no history)",
    )

    try:
        result = await llm_backend.complete(  # type: ignore[union-attr]
            [Message(role="user", content=prompt)], tier="worker"
        )
        
        # Handle both dict and string results (for mocks vs real API)
        if isinstance(result, dict):
            # If mock returned raw response data, use it
            if "content" in result and not isinstance(result["content"], str):
                 data = result["content"]
            elif "intent" in result:
                 data = result
            else:
                 text = str(result.get("content", ""))
                 data = json.loads(text) if text.strip().startswith("{") else {}
        else:
            text = str(result).strip()
            # Strip markdown code fences if present
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
            data = json.loads(text)

        si = StructuredIntent(
            intent=data.get("intent", "GENERAL").upper(),
            action=data.get("action", "CHAT").upper(),
            entity=data.get("entity"),
            needs_clarification=data.get("needs_clarification", False),
        )
        # Set legacy category
        si.raw_category = si.intent
        logger.info(
            "structured_intent: intent=%s action=%s entity=%r clarify=%s",
            si.intent, si.action, si.entity, si.needs_clarification,
        )
        return si

    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.warning("structured_intent parse error: %s", exc)
        # Fallback: use keyword-based classification
        from seahorse_ai.prompts.intent import (
            MEMORY_KEYWORDS, REALTIME_KEYWORDS,
        )
        if any(k.lower() in q_lower for k in MEMORY_KEYWORDS):
            return StructuredIntent(
                intent="PRIVATE_MEMORY", action="QUERY",
                raw_category="PRIVATE_MEMORY",
            )
        if any(k.lower() in q_lower for k in REALTIME_KEYWORDS):
            return StructuredIntent(
                intent="PUBLIC_REALTIME", action="SEARCH_WEB",
                raw_category="PUBLIC_REALTIME",
            )
        # Default to CHAT (slow path) for everything else, including mocks
        return StructuredIntent(intent="GENERAL", action="CHAT", raw_category="GENERAL")

    except Exception as exc:  # noqa: BLE001
        logger.error("structured_intent failed: %s", exc)
        return StructuredIntent(intent="GENERAL", action="CHAT", raw_category="GENERAL")


class FastPathRouter:
    """Execute simple actions directly — bypass the ReAct loop.

    Handles STORE, QUERY, and GREET without any additional LLM calls.
    Complex actions (SEARCH_WEB, SQL, CHAT, CLARIFY, UPDATE) fall through.
    """

    def __init__(self, tools: object, llm_backend: object = None) -> None:
        self._tools = tools
        self._llm = llm_backend  # Used by Phase 2 MemoryExtractor

    async def try_route(
        self,
        si: StructuredIntent,
        agent_id: str,
    ) -> AgentResponse | None:
        """Try to handle via fast path. Returns None if ReAct loop needed."""
        if si.needs_clarification:
            return None  # Let ReAct + LLM ask clarifying question

        if si.action not in _FAST_ACTIONS:
            return None  # Complex → ReAct loop

        if si.action == "GREET":
            return self._handle_greet()

        if si.action == "STORE" and si.entity:
            return await self._handle_store(si.entity, agent_id)

        if si.action == "QUERY" and si.entity:
            return await self._handle_query(si.entity, agent_id)

        if si.action == "CHAT":
            return self._handle_chat()

        return None

    def _handle_greet(self) -> AgentResponse:
        import random
        return AgentResponse(
            content=random.choice(_GREETINGS),
            steps=0,
            elapsed_ms=0,
        )

    def _handle_chat(self) -> AgentResponse:
        import random
        return AgentResponse(
            content=random.choice(_CHAT_FALLBACKS),
            steps=0,
            elapsed_ms=0,
        )

    async def _handle_store(
        self, entity: str, agent_id: str,
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
                    fact.fact_type, fact.importance, fact.text,
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
            logger.warning(
                "fast_path: MemoryExtractor unavailable (%s) — using regex split", exc
            )
            from seahorse_ai.tools.memory_extractor import MemoryFact
            items = _split_entities(text)
            return [MemoryFact(text=item, importance=3) for item in items]

    async def _handle_query(
        self, entity: str, agent_id: str,
    ) -> AgentResponse | None:
        """Search memory and synthesize an answer (Phase 4)."""
        try:
            from seahorse_ai.planner.memory_reasoner import MemoryReasoner
            reasoner = MemoryReasoner(llm_backend=self._llm, tools_registry=self._tools)
            return await reasoner.reason(query=entity, agent_id=agent_id)
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


def _format_memory_results(raw: str) -> str:
    """Convert raw memory_search output to natural Thai response.

    Input:  'Memory search results for: ...\n1. [Imp:3] [53.6% match] (Saved: ...) Packet A ราคา 1200'
    Output: 'จากข้อมูลที่บันทึกไว้ครับ:\n• Packet A ราคา 1200'
    """
    lines = raw.strip().split("\n")
    items: list[str] = []

    for line in lines:
        # Skip header line
        if line.startswith("Memory search") or not line.strip():
            continue
        # Extract the actual text after metadata
        # Format: "1. [Imp:3] [53.6% match] (Saved: 2026-03-08 15:36) Packet A ราคา 1200"
        match = re.search(r"\)\s+(.+)$", line)
        if match:
            items.append(match.group(1).strip())
        else:
            # Fallback: remove leading number and brackets
            cleaned = re.sub(r"^\d+\.\s*(\[.*?\]\s*)*(\(.*?\)\s*)*", "", line).strip()
            if cleaned:
                items.append(cleaned)

    if not items:
        return raw  # Fallback: return as-is

    if len(items) == 1:
        return f"จากข้อมูลที่บันทึกไว้ครับ:\n\n**{items[0]}**"

    bullet_list = "\n".join(f"  • {item}" for item in items)
    return f"จากข้อมูลที่บันทึกไว้ครับ ({len(items)} รายการ):\n\n{bullet_list}"

