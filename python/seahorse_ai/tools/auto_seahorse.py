"""seahorse_ai.tools.auto_seahorse — Complex multi-agent orchestration tools."""
from __future__ import annotations

import logging
from typing import Any

from seahorse_ai.tools.base import tool

logger = logging.getLogger(__name__)

@tool(
    "Execute Auto-Seahorse (multi-agent) to solve complex objectives "
    "like Research, Data Analysis, or HR."
)
async def execute_auto_seahorse(objective: str, context: str = "", team_hint: str | None = None) -> dict[str, Any]:
    """Run a specialized team based on the objective (Data, HR, or Research).
    
    Args:
        objective: The main goal (e.g., 'Analyze sales and make a dashboard' or 'Draft a job post').
        context: Optional additional background info.
        team_hint: Optional intent from planner to skip classification.
 
    """
    from seahorse_ai.llm import LLMClient
    from seahorse_ai.schemas import LLMConfig, Message
    from seahorse_ai.swarm import SeahorseCrew
    from seahorse_ai.teams import registry
    
    # Import teams to trigger registration via library.py
    import seahorse_ai.teams  # noqa: F401
    
    # Setup LLM
    llm = LLMClient(config=LLMConfig())
    
    # 1. Classify the objective into a Team (Selective skip)
    team_name = team_hint.upper() if team_hint else None
    
    # Map intents to registered names
    if team_name == "DATABASE":
        team_name = "DATA"
    
    if not team_name or team_name == "GENERAL":
        logger.info("Auto-Seahorse: Identifying team for objective: %s", objective)
        teams_list = ", ".join(registry.list_teams())
        team_prompt = f"""
        Identify the best specialized team for this objective: "{objective}"
        
        Available Teams:
        {teams_list}
        
        Return ONLY the team name (e.g., DATA, HR, or RESEARCH).
        """
        team_response = await llm.complete([Message(role="user", content=team_prompt)], tier="worker")
        team_name = str(team_response.get("content", "RESEARCH")).strip().strip('"').strip("'").upper()
    
    # Ensure team exists, fallback to RESEARCH
    team = registry.get(team_name) or registry.get("RESEARCH")
    if not team:
        raise RuntimeError("No teams available in registry, including default RESEARCH team.")
        
    logger.info("Auto-Seahorse: Selected Team: %s for objective: %s", team.name, objective)
    
    # 2. Get agents and tasks from the selected team
    agents, tasks = await team.get_agents_and_tasks(objective, llm)

    # 2.5 Inject language enforcement (Language lock)
    # If objective contains Thai characters, force the whole crew to reply in Thai.
    import re
    is_thai = bool(re.search(r'[\u0E00-\u0E7F]', objective))
    lang_instruction = "IMPORTANT: You MUST speak in THAI." if is_thai else "REPLY in the user's language."
    
    for agent in agents:
        agent.planner._identity_prompt = (agent.planner._identity_prompt or "") + f"\n\n{lang_instruction}"

    # 3. Form the Crew and kickoff
    crew = SeahorseCrew(agents=agents, tasks=tasks)
    return await crew.kickoff()
