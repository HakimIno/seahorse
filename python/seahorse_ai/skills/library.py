"""Library of core SeahorseSkills."""
from __future__ import annotations

from seahorse_ai.skills.base import SeahorseSkill, registry
from seahorse_ai.tools.web_search import web_search
from seahorse_ai.tools.browser import browser_scan
from seahorse_ai.tools.db import database_query, database_schema
from seahorse_ai.tools.python_interpreter import python_interpreter
from seahorse_ai.tools.memory import memory_search
from seahorse_ai.tools.viz import create_custom_chart
from seahorse_ai.tools.forecaster import forecast_sales

# 1. Web Research Skill
web_research_skill = SeahorseSkill(
    name="Web_Research",
    description="Ability to search the live web and scan websites for real-time data.",
    rules=[
        "For news, weather, or recent events, you MUST use `web_search` immediately.",
        "Prioritize information from search snippets. Only use `browser_scan` for deep details.",
        "Always cite your sources (e.g., BBC News) in the final report."
    ],
    tools=[web_search, browser_scan]
)

# 2. Database Access Skill
database_skill = SeahorseSkill(
    name="Database_Access",
    description="Ability to query corporate databases and analyze schemas.",
    rules=[
        "You MUST call `database_schema` before any query to verify table names.",
        "Never guess table names. Use the schema results to build accurate SQL.",
        "Always ensure data integrity and accuracy in your queries."
    ],
    tools=[database_query, database_schema]
)

# 3. Data Analysis Skill
analysis_skill = SeahorseSkill(
    name="Data_Analysis",
    description="Basic code execution and memory retrieval.",
    rules=[
        "Use the `python_interpreter` for basic math or data processing.",
        "ALWAYS check memory via `memory_search` if the user refers to past discussions."
    ],
    tools=[python_interpreter, memory_search]
)

# 4. ADVANCED Data Analysis Skill (NEW)
advanced_analysis_skill = SeahorseSkill(
    name="Advanced_Data_Analysis",
    description="Professional data science, visualization, and forecasting.",
    rules=[
        "Use `create_custom_chart` to generate premium visuals for your findings.",
        "Use `forecast_sales` when the user asks about future trends or predictions.",
        "Always perform Exploratory Data Analysis (EDA) before finalizing conclusions.",
        "Use a professional, data-driven tone. Explain the statistical significance if possible.",
        "Ensure charts use a modern color palette (Slate/Indigo) to look premium."
    ],
    tools=[python_interpreter, create_custom_chart, forecast_sales]
)

# Registration
registry.register(web_research_skill)
registry.register(database_skill)
registry.register(analysis_skill)
registry.register(advanced_analysis_skill)
