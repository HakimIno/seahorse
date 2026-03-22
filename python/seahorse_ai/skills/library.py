"""Library of core SeahorseSkills."""

from seahorse_ai.skills.base import SeahorseSkill, registry
from seahorse_ai.tools.system.browser import browser_scan
from seahorse_ai.tools.data.data_connectors import extract_sql_to_parquet, load_to_sql
from seahorse_ai.tools.data.data_profiler import data_profile
from seahorse_ai.tools.data.db import database_query, database_schema
from seahorse_ai.tools.visual.echarts_composer import echarts_composer
from seahorse_ai.tools.visual.echarts_viz import native_echarts_chart
from seahorse_ai.tools.business.forecaster import forecast_sales
from seahorse_ai.tools.internal.memory import memory_search
from seahorse_ai.tools.data.polars_analyst import native_polars_aggregate, polars_query
from seahorse_ai.tools.visual.table_viz import create_table_image
from seahorse_ai.tools.visual.viz import create_custom_chart
from seahorse_ai.tools.system.web_search import web_search

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

# 5. Data Engineering Skill
data_engineering_skill = SeahorseSkill(
    name="Data_Engineering",
    description="Autonomous data transformation, ETL pipeline orchestration, and data quality profiling.",
    rules=[
        "Use `polars_query` for all data transformations. It is the gold standard for performance and memory safety.",
        "Always perform an initial inspection or profiling of the source data before applying transformations.",
        "Ensure data type consistency across different sources (e.g., aligning CSV schemas with SQL tables).",
        "When loading data to a destination, verify schema compatibility using `database_schema` first.",
        "Clearly document all cleaning steps (e.g., null handling, type casting, or deduplication) performed on the data.",
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

# 6. BI Analyst Skill
bi_analyst_skill = SeahorseSkill(
    name="BI_Analyst",
    description="Professional data storytelling, advanced visualization, and strategic business reporting.",
    rules=[
        "SPEED: For Scatter/Bar/Line charts, IMMEDIATELY execute `polars_query` then `echarts_composer`.",
        "When plotting Scatter charts for large datasets (>1000 rows): Use a representative sample.",
        "NEVER 'guess' or 'approximate' statistical values. ALL numbers MUST match tool outputs.",
        "CHART TAG: You MUST include the `ECHART_JSON:/path/to/file.json` string on its own line.",
        "Provide a clear, strategic interpretation of the visual findings.",
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
registry.register(data_engineering_skill)
registry.register(bi_analyst_skill)
