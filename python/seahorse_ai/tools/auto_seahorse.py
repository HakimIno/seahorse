"""seahorse_ai.tools.auto_seahorse — Complex multi-agent orchestration tools."""
from __future__ import annotations

import logging

from seahorse_ai.swarm import CrewAgent, SeahorseCrew, SeahorseTask
from seahorse_ai.tools.base import SeahorseToolRegistry, tool

logger = logging.getLogger(__name__)

@tool(
    "Execute Auto-Seahorse (multi-agent) to solve complex objectives "
    "like Research, Data Analysis, or HR."
)
async def execute_auto_seahorse(objective: str, context: str = "") -> str:
    """Run a specialized team based on the objective (Data, HR, or Research).
    
    Args:
        objective: The main goal (e.g., 'Analyze sales and make a dashboard' or 'Draft a job post').
        context: Optional additional background info.

    """
    from seahorse_ai.llm import LLMClient
    from seahorse_ai.planner import ReActPlanner
    from seahorse_ai.schemas import LLMConfig, Message
    from seahorse_ai.tools import make_default_registry
    from seahorse_ai.tools.db import database_query, database_schema
    from seahorse_ai.tools.python_interpreter import python_interpreter
    from seahorse_ai.tools.viz import create_custom_chart
    
    # Setup LLM
    llm = LLMClient(config=LLMConfig())
    
    # 1. Classify the objective into a Team
    team_prompt = f"""
    Identify the best specialized team for this objective: "{objective}"
    
    Available Teams:
    - DATA: For database queries, dashboards, sales analysis, graphs/charts.
    - HR: For recruitment, job descriptions, labor laws, company culture.
    - RESEARCH: For market research, web search, technical reports (Default).
    
    Return ONLY the team name (DATA, HR, or RESEARCH).
    """
    team_response = await llm.complete([Message(role="user", content=team_prompt)], tier="worker")
    team_name = str(team_response.get("content", "RESEARCH")).strip().upper()
    if team_name not in ["DATA", "HR", "RESEARCH"]:
        team_name = "RESEARCH"
        
    logger.info("Auto-Seahorse: Selected Team: %s for objective: %s", team_name, objective)
    
    agents = []
    tasks = []
    
    if team_name == "DATA":
        # --- Data Team Setup ---
        # Data Engineer for querying
        eng_tools = SeahorseToolRegistry()
        eng_tools.register(database_query)
        eng_tools.register(database_schema)
        eng_planner = ReActPlanner(llm=llm, tools=eng_tools)
        
        engineer = CrewAgent(
            name="DataEngineer",
            role="Expert SQL & Database Engineer",
            goal=f"Extract raw data from the database for: {objective}",
            backstory="Master of SQL queries and schema understanding. Ensures data accuracy.",
            planner=eng_planner
        )
        
        # Visualizer for charting
        viz_tools = SeahorseToolRegistry()
        viz_tools.register(create_custom_chart)
        viz_tools.register(python_interpreter)
        viz_planner = ReActPlanner(llm=llm, tools=viz_tools)
        
        visualizer = CrewAgent(
            name="Visualizer",
            role="Data Storyteller & Visualization Specialist",
            goal=f"Turn raw data for {objective} into beautiful, professional charts and reports.",
            backstory="Specializes in creating elegant dashboards and synthesizing trends.",
            planner=viz_planner
        )
        
        task1 = SeahorseTask(
            description=f"Analyze the database schema and query the necessary data for {objective}.",
            expected_output="A summary of the raw data and key metrics identified.",
            agent_name="DataEngineer"
        )
        
        task2 = SeahorseTask(
            description=(
                f"Create a dashboard with charts (using chart tool) based on the data. "
                f"Use a dark/slate theme."
            ),
            expected_output="A professional markdown report with embedded charts.",
            agent_name="Visualizer"
        )
        
        agents = [engineer, visualizer]
        tasks = [task1, task2]

    elif team_name == "HR":
        # --- HR Team Setup ---
        hr_tools = make_default_registry()
        hr_planner = ReActPlanner(llm=llm, tools=hr_tools)
        
        recruiter = CrewAgent(
            name="Recruiter",
            role="Technical Talent Acquisition",
            goal=f"Draft highly attractive job descriptions for: {objective}",
            backstory="Expert in identifying top talent and understanding technical requirements.",
            planner=hr_planner
        )
        
        specialist = CrewAgent(
            name="HR_Specialist",
            role="Employee Relations & Policy Expert",
            goal=f"Ensure compliance and cultural alignment for: {objective}",
            backstory="Specialized in labor laws and workplace harmony.",
            planner=hr_planner
        )
        
        task1 = SeahorseTask(
            description=f"Draft initial requirements and responsibilities for {objective}.",
            expected_output="A structured list of skills and qualifications.",
            agent_name="Recruiter"
        )
        
        task2 = SeahorseTask(
            description=(
                "Refine the draft into a professional document. "
                "Ensure premium tone."
            ),
            expected_output="A polished HR document in markdown.",
            agent_name="HR_Specialist"
        )
        
        agents = [recruiter, specialist]
        tasks = [task1, task2]
    else:
        # --- Research Team Setup (Default) ---
        research_tools = make_default_registry() # Researcher needs everything
        researcher_planner = ReActPlanner(llm=llm, tools=research_tools)
        
        researcher = CrewAgent(
            name="Researcher",
            role="Senior Research Specialist",
            goal=f"Find information about: {objective}",
            backstory="Expert at deep-web research and finding non-obvious data points.",
            planner=researcher_planner
        )
        
        analyst_tools = SeahorseToolRegistry()
        analyst_tools.register(create_custom_chart) # Give analyst charts too!
        analyst_tools.register(python_interpreter)
        analyst_planner = ReActPlanner(llm=llm, tools=analyst_tools)
        
        analyst = CrewAgent(
            name="Analyst",
            role="Strategic Data Analyst",
            goal=f"Synthesize the findings for: {objective} into a professional report.",
            backstory="Specialized in turning raw data into strategic insights.",
            planner=analyst_planner
        )
        
        task1 = SeahorseTask(
            description=f"Conduct thorough research on {objective}.",
            expected_output="A list of 5-10 detailed bullet points of findings.",
            agent_name="Researcher"
        )
        
        task2 = SeahorseTask(
            description=f"Analyze the research results for {objective} and write a report.",
            expected_output="A professional markdown report.",
            agent_name="Analyst"
        )
        
        agents = [researcher, analyst]
        tasks = [task1, task2]

    # 3. Form the Crew and kickoff
    crew = SeahorseCrew(agents=agents, tasks=tasks)
    return await crew.kickoff()
