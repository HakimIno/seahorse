"""Library of core SeahorseSkills."""

from seahorse_ai.skills.base import SeahorseSkill, registry
from seahorse_ai.tools.browser import browser_scan
from seahorse_ai.tools.data_connectors import extract_sql_to_parquet, load_to_sql
from seahorse_ai.tools.data_profiler import data_profile
from seahorse_ai.tools.db import database_query, database_schema
from seahorse_ai.tools.echarts_composer import echarts_composer
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
        "Use `native_echarts_chart` for quick Bar/Line charts.",
        "Use `echarts_composer` (ECharts) for ANY complex or premium visuals (Scatter, Heatmap, etc.).",
        "**DEPRECATED**: Only use `create_custom_chart` (Matplotlib) if ECharts is impossible.",
        "Use `forecast_sales` when the user asks about future trends or predictions.",
        "Ensure charts use a modern color palette to look premium.",
        "Use `create_table_image` to present tabular data beautifully instead of simple Markdown.",
    ],
    tools=[polars_query, native_echarts_chart, echarts_composer, create_custom_chart, create_table_image, forecast_sales],
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

# 6. Data Engineering Skill (NEW)
data_engineering_skill = SeahorseSkill(
    name="Data_Engineering",
    description="Autonomous data transformation, ETL pipeline orchestration, and data quality profiling.",
    rules=[
        "Use `polars_query` for all data transformations. It is the gold standard for performance and memory safety.",
        "Always perform an initial inspection or profiling of the source data before applying transformations.",
        "Ensure data type consistency across different sources (e.g., aligning CSV schemas with SQL tables).",
        "When loading data to a destination, verify schema compatibility using `database_schema` first.",
        "Clearly document all cleaning steps (e.g., null handling, type casting, or deduplication) performed on the data.",
        "Prioritize 'Lazy' operations in Polars when dealing with datasets that might exceed memory (Big Data).",
        "CHART TAG: If asked for a visualization, use `echarts_composer` and include the `ECHART_JSON:/path/to/file.json` string on its own line at the end of your response.",
    ],
    tools=[
        polars_query, 
        native_polars_aggregate, 
        data_profile,
        extract_sql_to_parquet,
        load_to_sql,
        database_query, 
        database_schema, 
        web_search,
        echarts_composer
    ],
)

# 7. BI Analyst Skill (NEW)
bi_analyst_skill = SeahorseSkill(
    name="BI_Analyst",
    description="Professional data storytelling, advanced visualization, and strategic business reporting.",
    rules=[
        "SPEED: For Scatter/Bar/Line charts, IMMEDIATELY execute `polars_query` then `echarts_composer`. DO NOT narrate your plan or perform redundant research unless the data is unknown.",
        "When plotting Scatter charts for large datasets (>1000 rows): Use a representative sample of 2,000 to 5,000 rows. If the dataset exceeds this, prioritize density aggregation (e.g., DuckDB round/group by) to show trends without crashing.",
        "NEVER 'guess' or 'approximate' statistical values (Correlation, Mean, Max). ALL numbers in your summary MUST match the tool outputs exactly.",
        "If a tool result is [TRUNCATED], accept the current sample as the source of truth for your summary, but mention that it is a sample of the first X rows.",
        "CHART TAG: You MUST include the `ECHART_JSON:/path/to/file.json` string on its own line at the end of your response so the system can render it.",
        "Provide a clear, strategic interpretation of the visual findings in the final response.",
        "Include a 'title' and 'tooltip' in all ECharts configurations for better user experience.",
    ],
    tools=[
        echarts_composer,
        polars_query,
        native_polars_aggregate,
        data_profile,
        database_query,
        web_search
    ],
)

# Registration
registry.register(web_research_skill)
registry.register(database_skill)
registry.register(analysis_skill)
registry.register(advanced_analysis_skill)
registry.register(football_scout_skill)
registry.register(data_engineering_skill)
registry.register(bi_analyst_skill)
