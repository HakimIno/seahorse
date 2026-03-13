"""Library of core SeahorseSkills."""

from seahorse_ai.skills.base import SeahorseSkill, registry
from seahorse_ai.tools.browser import browser_scan
from seahorse_ai.tools.db import database_query, database_schema
from seahorse_ai.tools.forecaster import forecast_sales
from seahorse_ai.tools.memory import memory_search
from seahorse_ai.tools.echarts_viz import native_echarts_chart
from seahorse_ai.tools.polars_analyst import native_polars_aggregate, polars_query
from seahorse_ai.tools.viz import create_custom_chart
from seahorse_ai.tools.web_search import web_search

# 1. Web Research Skill
web_research_skill = SeahorseSkill(
    name="Web_Research",
    description="Ability to search the live web and scan websites for real-time data.",
    rules=[
        "For news, weather, or recent events, you MUST use `web_search` immediately.",
        "Prioritize information from search snippets. Only use `browser_scan` for deep details.",
        "Always cite your sources (e.g., BBC News) in the final report.",
    ],
    tools=[web_search, browser_scan],
)

# 2. Database Access Skill
database_skill = SeahorseSkill(
    name="Database_Access",
    description="Ability to query corporate databases and analyze schemas.",
    rules=[
        "You MUST call `database_schema` before any query to verify table names.",
        "Never guess table names. Use the schema results to build accurate SQL.",
        "Always ensure data integrity and accuracy in your queries.",
    ],
    tools=[database_query, database_schema],
)

# 3. Data Analysis Skill
analysis_skill = SeahorseSkill(
    name="Data_Analysis",
    description="Core data processing and memory retrieval.",
    rules=[
        "Prioritize `polars_query` for data transformation; it is faster than Python lists.",
        "Use `native_polars_aggregate` for large datasets to leverage Rust performance.",
        "ALWAYS check memory via `memory_search` if the user refers to past discussions.",
    ],
    tools=[polars_query, native_polars_aggregate, memory_search],
)

# 4. ADVANCED Data Analysis Skill (NEW)
advanced_analysis_skill = SeahorseSkill(
    name="Advanced_Data_Analysis",
    description="Professional data science, high-performance visualization, and forecasting.",
    rules=[
        "Use `native_echarts_chart` for premium, modern business visuals.",
        "Falls back to `create_custom_chart` (Matplotlib) ONLY if ECharts is not possible.",
        "Use `forecast_sales` when the user asks about future trends or predictions.",
        "Always perform Exploratory Data Analysis (EDA) using Polars before finalizing.",
        "Ensure charts use a modern color palette to look premium.",
    ],
    tools=[polars_query, native_echarts_chart, create_custom_chart, forecast_sales],
)

# Registration
registry.register(web_research_skill)
registry.register(database_skill)
registry.register(analysis_skill)
registry.register(advanced_analysis_skill)
