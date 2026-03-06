"""seahorse_ai.tools.auto_architect — Execution planner for strategies."""
from __future__ import annotations

import logging
from seahorse_ai.tools.base import tool

logger = logging.getLogger(__name__)

@tool(
    "Turn a winning strategy into an actionable code implementation plan. "
    "Provide the winning strategy text as input."
)
async def auto_architect(winning_strategy: str) -> str:
    """Generate a code implementation plan from a strategy."""
    logger.info("auto_architect: planning %d length strategy", len(winning_strategy))
    
    report = (
        f"### 🏗️ Auto-Architect: Implementation Plan\n\n"
        f"**Input Strategy:**\n{winning_strategy[:500]}...\n\n"
        "**Agent Instruction:** Please act as the Lead Engineer. Draft a Markdown document "
        "that breaks down EXACTLY which files need to be modified or created to implement "
        "this strategy, including step-by-step instructions. Output this plan directly to the user."
    )
    
    return report
