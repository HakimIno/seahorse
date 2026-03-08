"""seahorse_ai.prompts.intent — Intent classification for smart tool routing.

Two-tier system:
1. Fast keyword pre-check (microseconds, free)
2. Semantic LLM classification (only when ambiguous)

Intent Categories:
  GENERAL           → Greetings, simple chat, coding, math, writing
  PUBLIC_REALTIME   → Market data, news, weather, live scores
  PRIVATE_MEMORY    → Internal products, past conversations, personal data
  DATABASE          → Corporate database queries
"""
from __future__ import annotations

# ── Tier 0: Greeting / chit-chat fast-path ────────────────────────────────────
# These must be checked FIRST — before REALTIME — to prevent false positives.
# "Hi", "Hello" etc. are pure greetings, never real-time data requests.

GREETING_PATTERNS: tuple[str, ...] = (
    "hi", "hello", "hey", "howdy", "greetings",
    "สวัสดี", "หวัดดี", "ดีจ้า", "ดีครับ", "ดีค่ะ",
    "ขอบคุณ", "thank you", "thanks", "good morning",
    "good afternoon", "good evening", "good night",
    "ลาก่อน", "bye", "goodbye", "see you",
    "เป็นยังไงบ้าง", "how are you", "what's up",
)

# ── Tier 1: Fast keyword pre-screening ────────────────────────────────────────
# HIGH CONFIDENCE signals — no ambiguity expected.

REALTIME_KEYWORDS: tuple[str, ...] = (
    # Thai — unambiguously public real-time data
    "ข่าว", "ราคาหุ้น", "ดัชนีหุ้น", "อากาศ", "ล่าสุด",
    "บิทคอยน์", "คริปโต", "ดัชนี", "ทองคำวันนี้", "น้ำมันวันนี้",
    "ทองวันนี้", "หุ้นวันนี้",
    # English — unambiguously public real-time data
    "breaking news", "stock price", "market price", "weather forecast",
    "cryptocurrency", "bitcoin price", "nba score", "premier league",
    "today's news", "latest news",
    "stock market", "stock performance",
)

# Note: "วันนี้" removed — too ambiguous ("วันนี้ฉันมีนัด" is NOT realtime)

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
# Used when Tier 0 and Tier 1 keywords don't provide a confident classification.

INTENT_CLASSIFY_PROMPT = """\
You are a routing classifier for an AI agent. Classify the user query into ONE category.

Categories:
- GENERAL: Greetings, simple chat, questions, coding, writing, math, general knowledge
- PUBLIC_REALTIME: Public market prices (gold/crypto/stocks), news feeds, weather, live scores
- PRIVATE_MEMORY: Internal business data, product prices set by user, past conversations
- DATABASE: Queries about corporate database tables, sales figures, customer records

Important rules:
- Short greetings ("Hi", "Hello", "สวัสดี", "ขอบคุณ") → ALWAYS GENERAL
- "ราคาทอง" or "Gold price today" → PUBLIC_REALTIME
- "ราคา [internal product]" (Package A/B, Plan X) → PRIVATE_MEMORY
- "ยอดขาย" or "sales data" → DATABASE
- "เขียนโค้ด", "explain X", general questions → GENERAL

Query: "{query}"

Respond with ONLY one of: GENERAL, PUBLIC_REALTIME, PRIVATE_MEMORY, DATABASE
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
    "Only fall back to `web_search` if memory returns empty AND the topic is public data."
)


async def classify_intent(query: str, llm_backend: object | None = None) -> str:
    """Classify query intent. Returns one of: PUBLIC_REALTIME, PRIVATE_MEMORY, DATABASE, GENERAL.

    Priority:
      Tier 0: Greeting fast-path → GENERAL immediately (prevents news hallucination)
      Tier 1: Keyword matching → PUBLIC_REALTIME or PRIVATE_MEMORY
      Tier 2: LLM classification for ambiguous cases
    """
    q_lower = query.lower().strip()

    # Tier 0: Greeting detection — check BEFORE realtime keywords
    # This prevents "Hi AI" from triggering PUBLIC_REALTIME via LLM fallback
    if _is_greeting(q_lower):
        return "GENERAL"

    # Tier 1: Fast path: unambiguous REALTIME signals
    if any(k.lower() in q_lower for k in REALTIME_KEYWORDS):
        return "PUBLIC_REALTIME"

    # Tier 1: Fast path: unambiguous MEMORY signals
    if any(k.lower() in q_lower for k in MEMORY_KEYWORDS):
        return "PRIVATE_MEMORY"

    # Tier 2: Slow path: ambiguous — use LLM if available
    if llm_backend is not None:
        try:
            from seahorse_ai.schemas import Message
            prompt = INTENT_CLASSIFY_PROMPT.format(query=query)
            result = await llm_backend.complete(  # type: ignore[union-attr]
                [Message(role="user", content=prompt)], tier="worker"
            )
            text = str(result).strip().upper()
            for cat in ("PUBLIC_REALTIME", "PRIVATE_MEMORY", "DATABASE", "GENERAL"):
                if cat in text:
                    return cat
        except Exception:  # noqa: BLE001
            pass

    return "GENERAL"


def _is_greeting(q_lower: str) -> bool:
    """Return True if the query is primarily a greeting or simple chit-chat.

    Checks both exact matches and prefix matches for short greeting-only messages.
    """
    # Exact or starts-with match for very short messages (≤ 3 words)
    words = q_lower.split()
    if len(words) <= 3:
        for pattern in GREETING_PATTERNS:
            if q_lower.startswith(pattern) or q_lower == pattern:
                return True
    return False
