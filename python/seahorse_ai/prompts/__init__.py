"""seahorse_ai.prompts — Layered prompt engineering for Seahorse Agent.

Layer architecture:
  core.py       — Persona, date injection, base rules (~30 lines)
  tool_rules.py — Tool-specific decision rules and conflict resolution
  few_shot.py   — High-quality example Q&A for tool selection
  confidence.py — Confidence calibration and anti-hallucination guards

Usage:
    from seahorse_ai.prompts import build_system_prompt, classify_intent
    from seahorse_ai.prompts import MEMORY_KEYWORDS, REALTIME_KEYWORDS
"""
from __future__ import annotations

from seahorse_ai.prompts.core import build_system_prompt
from seahorse_ai.prompts.intent import (
    MEMORY_KEYWORDS,
    MEMORY_NUDGE,
    REALTIME_KEYWORDS,
    REALTIME_NUDGE,
    classify_intent,
)
from seahorse_ai.prompts.strategy import (
    STRATEGY_GENERATION_PROMPT,
    STRATEGY_NUDGE,
)

__all__ = [
    "build_system_prompt",
    "classify_intent",
    "MEMORY_KEYWORDS",
    "REALTIME_KEYWORDS",
    "MEMORY_NUDGE",
    "REALTIME_NUDGE",
    "STRATEGY_GENERATION_PROMPT",
    "STRATEGY_NUDGE",
]
