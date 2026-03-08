"""seahorse_ai.prompts.intent — Intent classification for smart tool routing.

Replaces the old keyword-only heuristic with a two-tier system:
1. Fast keyword pre-check (microseconds, free)
2. Semantic LLM classification (used only when ambiguous)

Intent Categories:
  PUBLIC_REALTIME   → Market data, news, weather, scores
  PRIVATE_MEMORY    → Internal products, past conversations, personal data
  DATABASE          → Corporate database queries
  GENERAL           → General knowledge, coding, writing tasks
"""
from __future__ import annotations

# ── Tier 1: Fast keyword pre-screening ────────────────────────────────────────
# These are HIGH CONFIDENCE signals — no ambiguity expected.

REALTIME_KEYWORDS: tuple[str, ...] = (
    # Thai — unambiguously public real-time data
    "ข่าว", "วันนี้", "ราคาหุ้น", "ดัชนีหุ้น", "อากาศ", "ล่าสุด",
    "บิทคอยน์", "คริปโต", "ดัชนี", "ทองคำวันนี้", "น้ำมันวันนี้",
    # English — unambiguously public real-time data
    "breaking news", "stock price", "market price", "weather forecast",
    "cryptocurrency", "bitcoin price", "nba score", "premier league",
    "today's news", "latest news",
    "stock market", "stock performance",
)

MEMORY_KEYWORDS: tuple[str, ...] = (
    # Thai — clearly referring to private/stored context
    "ที่เคยคุย", "ที่บอกไป", "ก่อนหน้า", "ครั้งที่แล้ว", "จำได้ไหม",
    "ที่เก็บไว้", "เดิม", "แก้ไข", "อัปเดต", "เปลี่ยนข้อมูล",
    "เมื่อวาน", "ที่เราคุย", "เปลี่ยนราคา", "เปลี่ยน", "จำไว้",
    # English — clearly referring to private/stored context
    "we discussed", "you remember", "last time", "previously discussed",
    "stored memory", "update the price", "change the record",
    "update price", "change price", "internal",
)

# ── Tier 2: LLM Semantic Intent Classification ─────────────────────────────────
# Used when keywords are ambiguous (e.g. "ราคา" alone is ambiguous).

INTENT_CLASSIFY_PROMPT = """\
You are a routing classifier for an AI agent. Classify the user query into ONE category.

Categories:
- PUBLIC_REALTIME: Public market prices, news, weather, live scores, global events
- PRIVATE_MEMORY: Internal business data, product prices set by user, past conversations
- DATABASE: Queries about corporate database tables, sales figures, customer records
- GENERAL: Coding, writing, math, general knowledge (no special tool needed first)

Rules:
- "ราคาทอง" or "Gold price" → PUBLIC_REALTIME
- "ราคา [product name user mentioned before]" → PRIVATE_MEMORY
- "ยอดขาย" or "sales" when a database is connected → DATABASE
- "เขียนโค้ด" or "explain X" → GENERAL

Query: "{query}"

Respond with ONLY one of: PUBLIC_REALTIME, PRIVATE_MEMORY, DATABASE, GENERAL
"""

# ── Nudge messages injected into the conversation ─────────────────────────────

REALTIME_NUDGE = (
    "[SYSTEM] This query requires current public data. "
    "Your training data is outdated. "
    "You MUST call `web_search` NOW before answering."
)

MEMORY_NUDGE = (
    "[SYSTEM] This query refers to previously stored information. "
    "You MUST call `memory_search` NOW before checking the web. "
    "Only fall back to `web_search` if memory returns empty results."
)


async def classify_intent(query: str, llm_backend: object | None = None) -> str:
    """Classify query intent. Returns one of: PUBLIC_REALTIME, PRIVATE_MEMORY, DATABASE, GENERAL.

    Uses fast keyword check first; falls back to LLM classification if ambiguous.
    """
    q_lower = query.lower()

    # Fast path: unambiguous REALTIME signals
    if any(k.lower() in q_lower for k in REALTIME_KEYWORDS):
        return "PUBLIC_REALTIME"

    # Fast path: unambiguous MEMORY signals
    if any(k.lower() in q_lower for k in MEMORY_KEYWORDS):
        return "PRIVATE_MEMORY"

    # Slow path: ambiguous — use LLM if available
    if llm_backend is not None:
        try:
            from seahorse_ai.schemas import Message
            prompt = INTENT_CLASSIFY_PROMPT.format(query=query)
            result = await llm_backend.complete(  # type: ignore[union-attr]
                [Message(role="user", content=prompt)], tier="worker"
            )
            # Normalize string result
            text = str(result).strip().upper()
            for cat in ("PUBLIC_REALTIME", "PRIVATE_MEMORY", "DATABASE", "GENERAL"):
                if cat in text:
                    return cat
        except Exception:  # noqa: BLE001
            pass

    return "GENERAL"
