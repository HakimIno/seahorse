"""seahorse_ai.prompts.core — Concise core persona and base rules.

Kept deliberately short to avoid the "Lost in the Middle" effect.
Only essential rules that apply universally are included here.
Tool-specific rules → tool_rules.py
Examples → few_shot.py
Confidence → confidence.py
"""
from __future__ import annotations

import datetime
import os

from seahorse_ai.prompts.confidence import CONFIDENCE_RULES, SELF_CHECK_PROMPT
from seahorse_ai.prompts.few_shot import FEW_SHOT_TOOL_EXAMPLES
from seahorse_ai.prompts.tool_rules import TOOL_RULES


def build_system_prompt() -> str:
    """Build a complete system prompt by composing all layers.

    Called fresh on every agent run so the date is always accurate.
    """
    today = datetime.date.today().strftime("%A, %B %d, %Y")
    db_type = os.getenv("SEAHORSE_DB_TYPE", "sqlite")

    return _CORE_PERSONA.format(today=today, db_type=db_type) + (
        "\n\n" + TOOL_RULES
        + "\n\n" + FEW_SHOT_TOOL_EXAMPLES
        + "\n\n" + CONFIDENCE_RULES
        + "\n\n" + SELF_CHECK_PROMPT
    )


# ── Core Persona (kept short — ≤30 lines) ─────────────────────────────────────
_CORE_PERSONA = """\
You are Seahorse Agent — a high-performance AI with real-time web access, \
long-term memory, and corporate database connectivity.

Today's date: {today}
Environment: Connected to a **{db_type}** corporate database.

## Core Principles
1. **Truth over Speed**: Never fabricate facts. If you don't know, say so.
2. **Tool-first**: Always use the right tool before answering. Do not guess.
3. **Memory before Web**: For internal/private data, check memory BEFORE searching the web.
4. **Strategy Adherence**: If a [STRATEGY PLAN] is in context, follow its steps.
5. **Atomic Memory**: Store one fact per `memory_store` call — never combine unrelated facts.
"""
