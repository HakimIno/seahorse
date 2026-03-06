"""seahorse_ai.tools.strategy_engine — Multi-agent debate for one-up strategy."""
from __future__ import annotations

import logging
from seahorse_ai.tools.base import tool

logger = logging.getLogger(__name__)

@tool(
    "Simulate a War Room debate to invent a 'one-up' feature or strategy to beat a competitor. "
    "Input should be raw intelligence (strengths/weaknesses) gathered from competitor_radar."
)
async def war_room(competitor_intelligence: str) -> str:
    """Run a multi-agent debate to formulate a winning strategy."""
    logger.info("war_room: analyzing intelligence length=%d", len(competitor_intelligence))
    
    # Normally we would inject the active LLM. Since tools don't receive LLMs natively yet,
    # we return a formatted prompt for the planner loop to handle, OR if we had a global LLM
    # instance, we could use it here.
    
    # For now, we will return the "Debate Instruction" back to the main ReAct loop
    # so the Agent itself acts as the War Room using its existing LLM.
    
    report = (
        f"### ⚔️ Entering the War Room\n\n"
        f"**Input Data:**\n{competitor_intelligence[:2000]}...\n\n"
        "**Agent Instruction:** Please embody 3 personas: The Visionary, "
        "The Critic, and The Engineer. Debate the input data and output a "
        "'Winning Strategy' that exploits their weakness or one-ups their "
        "feature. Do NOT just copy them. After deciding on the Winning "
        "Strategy, proceed to use the Auto-Architect tool."
    )
    
    return report
