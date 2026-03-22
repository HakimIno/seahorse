"""seahorse_ai.tools.business.strategy_engine — Multi-agent debate for one-up strategy."""

from __future__ import annotations

import logging
from typing import Any

from seahorse_ai.core.schemas import Message
from seahorse_ai.tools.base import tool

logger = logging.getLogger(__name__)


@tool(
    "Simulate a War Room debate to invent a 'one-up' feature or strategy to beat a competitor. "
    "Input should be raw intelligence (strengths/weaknesses) gathered from competitor_radar."
)
async def war_room(competitor_intelligence: str, _llm: Any = None) -> str:
    """Run a multi-agent debate using a nested LLM to formulate a winning strategy."""
    logger.info("war_room: analyzing intelligence length=%d", len(competitor_intelligence))

    if _llm is None:
        return "Error: No internal LLM injected into war_room tool."

    prompt = (
        f"You are inside a virtual War Room.\n"
        f"Input Data:\n{competitor_intelligence[:2000]}\n\n"
        f"Embody 3 personas: The Visionary (idea generator), The Critic (finds flaws), and The Engineer (execution). "
        f"Debate the intelligence and output a final 'Winning Strategy' that exploits the competitor's weakness. "
        f"Provide only the final agreed-upon strategy without excessive chatter."
    )

    try:
        # Nested LLM call internal to the tool!
        response = await _llm.complete([Message(role="user", content=prompt)], tier="thinker")
        final_strategy = response.get("content", str(response))
        return f"### ⚔️ War Room Consensus\n\n{final_strategy}"
    except Exception as e:
        logger.error(f"War Room internal LLM failed: {e}")
        return f"War Room debate failed: {e}"
