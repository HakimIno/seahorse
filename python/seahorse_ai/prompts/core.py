"""seahorse_ai.prompts.core — Concise core persona and base rules.

Layered architecture for high-performance agent behavior.
This module now supports modular SeahorseSkills for dynamic prompt assembly.
"""

from __future__ import annotations

import datetime
import os
from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from seahorse_ai.skills.base import SeahorseSkill

@lru_cache(maxsize=10)
def _load_manifest(name: str) -> str:
    """Load a prompt manifest from the manifests/ directory."""
    manifest_path = os.path.join(os.path.dirname(__file__), "manifests", f"{name}.md")
    try:
        with open(manifest_path, encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        # Fallback empty string if loading fails
        return ""

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
    if tone == "CASUAL":
        base_persona = _load_manifest("casual_identity") or _CASUAL_FALLBACK
    else:
        base_persona = _load_manifest("identity") or _CORE_FALLBACK
        
    prompt = base_persona.format(today=today, db_type=db_type)

    # 2. Efficiency nudge — universal, not intent-specific
    prompt += (
        "\n## Efficiency"
        "\n- Use the minimum number of tool calls needed. Don't over-research."
        "\n- After getting good data from tools, synthesize and respond immediately."
        "\n- Only create charts or visualizations when explicitly requested."
    )

    # 3. Dynamic Skill Guidelines
    if skills:
        prompt += "\n## Your Active Skills\n"
        for skill in skills:
            prompt += skill.get_prompt_snippet() + "\n"
    else:
        prompt += "\n" + _load_manifest("tool_rules")

    # 4. Quality layers
    prompt += (
        "\n\n" + _load_manifest("few_shot") + 
        "\n\n" + _load_manifest("confidence")
    )

    return prompt


# ── Fallback Personas ────────────────────────────────────────────────────────
_CORE_FALLBACK = """\
You are Seahorse Agent — a high-performance AI with real-time web access, \\
long-term memory, and corporate database connectivity.

Today's date: {today}
Environment: Connected to a **{db_type}** corporate database.

## Core Principles
1. **Absolute Data Fidelity**: NEVER fabricate data.
2. **Tool-first**: Always use the right tool before answering.
"""

_CASUAL_FALLBACK = """\
You are Seahorse Agent, but currently in a **Friendly & Casual** mode. 
Tone is warm, relaxed, and conversational.
Today's date: {today}
"""
