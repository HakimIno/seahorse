"""Library of core SeahorseSkills."""

from seahorse_ai.skills.base import SeahorseSkill, registry
from seahorse_ai.tools.browser import browser_scan
from seahorse_ai.tools.db import database_query, database_schema
from seahorse_ai.tools.echarts_viz import native_echarts_chart
from seahorse_ai.tools.football_stats import (
    calculatebetvalue,
    fetchlivematch,
    fetchliveodds,
    geth2hresults,
    getmatchintel,
    kellycriterion,
    predictmatchoutcome,
)
from seahorse_ai.tools.forecaster import forecast_sales
from seahorse_ai.tools.memory import memory_search
from seahorse_ai.tools.polars_analyst import native_polars_aggregate, polars_query
from seahorse_ai.tools.table_viz import create_table_image
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
        "Use `create_table_image` to present tabular data beautifully instead of simple Markdown.",
    ],
    tools=[polars_query, native_echarts_chart, create_custom_chart, create_table_image, forecast_sales],
)

# 5. Football Scout Skill (NEW)
football_scout_skill = SeahorseSkill(
    name="Football_Scout",
    description="Deep analysis and prediction of football matches using statistics and real-time intel.",
    rules=[
        "Use `fetchlivematch` and `fetchliveodds` for real-time data instead of web search if possible.",
        "Use `geth2hresults` to understand historical trends between teams.",
        "Always call `getmatchintel` to check for injuries or tactical changes before predicting.",
        "Use `calculatebetvalue` and `kellycriterion` for bankroll management and finding an edge.",
        "When explaining predictions, cite specific factors like xG and injury reports.",
    ],
    tools=[
        geth2hresults, 
        getmatchintel, 
        predictmatchoutcome, 
        fetchlivematch, 
        fetchliveodds, 
        calculatebetvalue, 
        kellycriterion,
        web_search
    ],
)

# Registration
registry.register(web_research_skill)
registry.register(database_skill)
registry.register(analysis_skill)
registry.register(advanced_analysis_skill)
registry.register(football_scout_skill)
