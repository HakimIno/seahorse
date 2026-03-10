"""seahorse_ai.tools.auto_seahorse — Complex multi-agent orchestration tools."""
from __future__ import annotations

import logging
from seahorse_ai.swarm import CrewAgent, SeahorseTask, SeahorseCrew
from seahorse_ai.tools.base import tool, SeahorseToolRegistry
from seahorse_ai.planner import LLMBackend, ToolRegistry

logger = logging.getLogger(__name__)

@tool("Execute Auto-Seahorse (multi-agent) to solve a complex objective. Useful for research + reporting.")
async def execute_auto_seahorse(objective: str, context: str = "") -> str:
    """Run a specialized team (Researcher and Analyst).
    
    Args:
        objective: The main goal (e.g., 'Research EV market in Thailand').
        context: Optional additional background info.
    """
    from seahorse_ai.llm import LLMClient
    from seahorse_ai.schemas import LLMConfig
    from seahorse_ai.tools import make_default_registry
    from seahorse_ai.planner import ReActPlanner
    
    # Setup LLM (using thinker tier for orchestration)
    llm = LLMClient(config=LLMConfig()) # Default to worker tier LLM for speed
    
    # 1. Define Agents
    research_tools = make_default_registry() # Researcher needs web search
    researcher_planner = ReActPlanner(llm=llm, tools=research_tools)
    researcher = CrewAgent(
        name="Researcher",
        role="Senior Research Specialist",
        goal=f"Find the most relevant and up-to-date information about: {objective}",
        backstory="Expert at deep-web research and finding non-obvious data points.",
        planner=researcher_planner
    )
    
    analyst_tools = SeahorseToolRegistry() # Analyst just needs reasoning + maybe python
    from seahorse_ai.tools.python_interpreter import python_interpreter
    analyst_tools.register(python_interpreter)
    analyst_planner = ReActPlanner(llm=llm, tools=analyst_tools)
    analyst = CrewAgent(
        name="Analyst",
        role="Strategic Data Analyst",
        goal=f"Synthesize the research findings for: {objective} into a professional report.",
        backstory="Specialized in turning raw data into strategic insights and clear reports.",
        planner=analyst_planner
    )
    
    # 2. Define Tasks
    task1 = SeahorseTask(
        description=f"Conduct thorough research on {objective}. Focus on current year developments.",
        expected_output="A list of 5-10 detailed bullet points of findings.",
        agent_name="Researcher"
    )
    
    task2 = SeahorseTask(
        description=f"Analyze the research results for {objective} and write a comprehensive report.",
        expected_output="A professional markdown report with clear headers and analysis.",
        agent_name="Analyst"
    )
    
    # 3. Form the Crew and kickoff
    crew = SeahorseCrew(agents=[researcher, analyst], tasks=[task1, task2])
    
    logger.info("Auto-Seahorse: Kickoff for objective: %s", objective)
    result = await crew.kickoff()
    return result
