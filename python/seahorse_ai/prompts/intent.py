"""seahorse_ai.prompts.intent — Intent classification for smart tool routing.

Two-tier system:
1. Fast keyword pre-check (microseconds, free)
2. Semantic LLM classification (only when ambiguous)

Intent Categories:
  GENERAL           → Greetings, simple chat, coding, math, writing
  PUBLIC_REALTIME   → Market data, news, weather, live scores
  PRIVATE_MEMORY    → Internal products, past conversations, personal data
  DATABASE          → Corporate database
"""

from __future__ import annotations

import json
import os
from functools import lru_cache

@lru_cache(maxsize=1)
def load_intent_config():
    """Load intent configuration from JSON manifest."""
    config_path = os.path.join(os.path.dirname(__file__), "intent_config.json")
    try:
        with open(config_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        # Fallback empty config if loading fails
        return {
            "GREETING_PATTERNS": [],
            "REALTIME_KEYWORDS": [],
            "MEMORY_KEYWORDS": [],
            "NUDGES": {}
        }

def get_intent_patterns():
    config = load_intent_config()
    return (
        tuple(config.get("GREETING_PATTERNS", [])),
        tuple(config.get("REALTIME_KEYWORDS", [])),
        tuple(config.get("MEMORY_KEYWORDS", [])),
        config.get("NUDGES", {})
    )

GREETING_PATTERNS, REALTIME_KEYWORDS, MEMORY_KEYWORDS, NUDGES = get_intent_patterns()
REALTIME_NUDGE = NUDGES.get("PUBLIC_REALTIME", "")
MEMORY_NUDGE = NUDGES.get("PRIVATE_MEMORY", "")


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

    # Tier 2: Slow path (REMOVED)
    # Semantic classification is now handled by the Structured Intent pipeline (FastPath).
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
