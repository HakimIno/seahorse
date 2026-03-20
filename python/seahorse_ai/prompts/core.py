"""seahorse_ai.prompts.core — Concise core persona and base rules.

Layered architecture for high-performance agent behavior.
This module now supports modular SeahorseSkills for dynamic prompt assembly.
"""

from __future__ import annotations

import datetime
import os
from typing import TYPE_CHECKING

from seahorse_ai.prompts.confidence import CONFIDENCE_RULES, SELF_CHECK_PROMPT
from seahorse_ai.prompts.few_shot import FEW_SHOT_TOOL_EXAMPLES

if TYPE_CHECKING:
    from seahorse_ai.skills.base import SeahorseSkill


def build_system_prompt(
    skills: list[SeahorseSkill] | None = None, tone: str = "PROFESSIONAL", intent: str = "GENERAL"
) -> str:
    """Build a complete system prompt by composing layers and active skills.

    Args:
        skills: Optional list of SeahorseSkill objects assigned to the agent.
        tone: The tone of the conversation (PROFESSIONAL or CASUAL).
        intent: The detected intent (GENERAL, PUBLIC_REALTIME, PRIVATE_MEMORY, DATABASE).

    Returns:
        A formatted system prompt string.

    """
    today = datetime.date.today().strftime("%A, %B %d, %Y")
    db_type = os.getenv("SEAHORSE_DB_TYPE", "sqlite")

    # 1. Base Identity & Tone
    base_persona = _CASUAL_PERSONA if tone == "CASUAL" else _CORE_PERSONA
    prompt = base_persona.format(today=today, db_type=db_type)

    # 2. Intent-specific expansion
    if intent in ("DATABASE", "PRIVATE_MEMORY"):
        prompt += (
            "\n## Deep Analysis Mode\n"
            "- You are in Thorough Expert mode. Prioritize depth, accuracy, and immediate action over redundant explanations.\n"
            "- Do NOT narrate your planning or research steps to the user. Just execute and provide the final result."
        )

    # 3. Dynamic Skill Guidelines (Modular Filtering)
    # If intent is GENERAL or GREET, we skip most heavy tool rules to save tokens
    if intent in ("GENERAL", "GREET") and tone != "CASUAL":
        prompt += (
            "\n## Guidelines\n- You are currently in Chat Mode. Answer naturally and concisely."
        )
        return prompt

    if skills:
        prompt += "\n## Guidelines for Your Skills\n"
        for skill in skills:
            # Future: add skill.is_relevant(intent)
            prompt += skill.get_prompt_snippet() + "\n"
    else:
        # Fallback to legacy tool rules if no skills provided
        from seahorse_ai.prompts.tool_rules import TOOL_RULES

        prompt += "\n" + TOOL_RULES

    # 3. Static Layers (Confidence, Examples, Quality)
    prompt += (
        "\n\n" + FEW_SHOT_TOOL_EXAMPLES + "\n\n" + CONFIDENCE_RULES + "\n\n" + SELF_CHECK_PROMPT
    )

    return prompt


# ── Core Persona (kept short — ≤30 lines) ─────────────────────────────────────
_CORE_PERSONA = """\
You are Seahorse Agent — a high-performance AI with real-time web access, \
long-term memory, and corporate database connectivity.

Today's date: {today}
Environment: Connected to a **{db_type}** corporate database.

## Core Principles
1. **Absolute Data Fidelity**: NEVER fabricate data, dates, or results. Use the provided tool results EXACTLY as they are. If a tool fails, report the failure; do not invent "sample" data.
2. **No Image Hallucination**: NEVER generate markdown image links (e.g., `![chart](...)`). The system handles image delivery. Just describe the results in text.
3. **Tool-first**: Always use the right tool before answering. Do not guess.
4. **Memory before Web**: For internal/private data, check memory BEFORE searching the web.
5. **Strategy Adherence**: If a [STRATEGY PLAN] is in context, follow its steps.
"""

# ── Alternate Personas ────────────────────────────────────────────────────────

_CASUAL_PERSONA = """\
You are Seahorse Agent, but currently in a **Friendly & Casual** mode. 
While you still have access to your tools, your tone is warm, relaxed, and conversational.

Today's date: {today}

## Casual Principles
1. **Be Warm**: Use emojis (😊, 👋, ✨) naturally. Be helpful but approachable.
2. **Contextual Intelligence**: If the user wants to chat or play, engage with them.
3. **Implicit Tooling**: You can still use tools (memory/web) but report findings in a less rigid way.
4. **Language**: Match the user's language (Thai/English) and slang.
"""
