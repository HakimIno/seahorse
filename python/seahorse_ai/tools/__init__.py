"""seahorse_ai.tools — tool registry and built-in tools.

Exports
-------
SeahorseToolRegistry   : registry class
ToolSpec               : tool metadata model
tool                   : @tool decorator
make_default_registry  : returns a registry with all built-in tools registered
"""

from seahorse_ai.tools.auto_architect import auto_architect
from seahorse_ai.tools.auto_seahorse import execute_auto_seahorse
from seahorse_ai.tools.base import SeahorseToolRegistry, ToolSpec, tool
from seahorse_ai.tools.browser import (
    browser_close,
    browser_scan,
    browser_scrape,
    browser_screenshot,
)
from seahorse_ai.tools.business_math import (
    calculate_margin,
    calculate_promo_impact,
)
from seahorse_ai.tools.competitor_radar import competitor_radar
from seahorse_ai.tools.db import database_query, database_schema
from seahorse_ai.tools.duckdb_analyst import duckdb_sql, sql_to_polars
from seahorse_ai.tools.filesystem import list_files, read_file, write_file
from seahorse_ai.tools.graph_memory import (
    graph_search_neighbors,
    graph_store_triple,
)
from seahorse_ai.tools.football_stats import (
    calculatebetvalue,
    comparemarketodds,
    fetchlivematch,
    fetchliveodds,
    geth2hresults,
    getmatchintel,
    getupcomingfixtures,
    kellycriterion,
    predictmatchoutcome,
    searchfixture,
    searchleague,
)
from seahorse_ai.tools.forecaster import forecast_sales
from seahorse_ai.tools.integrations import (
    google_calendar_add_event,
    slack_send_message,
)
from seahorse_ai.tools.mcp_client import load_mcp_tools
from seahorse_ai.tools.memory import (
    memory_clear,
    memory_delete,
    memory_feedback,
    memory_search,
    memory_store,
)
from seahorse_ai.tools.polars_analyst import (
    convert_to_parquet,
    polars_inspect_join,
    polars_profile,
    polars_query,
)
from seahorse_ai.tools.python_interpreter import python_interpreter
from seahorse_ai.tools.strategy_engine import war_room
from seahorse_ai.tools.table_viz import create_table_image
from seahorse_ai.tools.viz import create_custom_chart
from seahorse_ai.tools.web_search import web_search

__all__ = [
    "SeahorseToolRegistry",
    "ToolSpec",
    "tool",
    "make_default_registry",
    "load_mcp_tools",
    # individual tools (for custom registries)
    "web_search",
    "python_interpreter",
    "list_files",
    "read_file",
    "write_file",
    "memory_store",
    "memory_search",
    "memory_feedback",
    "memory_delete",
    "memory_clear",
    "browser_scan",
    "browser_scrape",
    "browser_screenshot",
    "browser_close",
    "competitor_radar",
    "war_room",
    "auto_architect",
    "slack_send_message",
    "google_calendar_add_event",
    "database_query",
    "database_schema",
    "calculate_promo_impact",
    "calculate_margin",
    "create_custom_chart",
    "create_table_image",
    "forecast_sales",
    "execute_auto_seahorse",
    "polars_query",
    "polars_profile",
    "polars_inspect_join",
    "convert_to_parquet",
    "duckdb_sql",
    "sql_to_polars",
    "geth2hresults",
    "getmatchintel",
    "getupcomingfixtures",
    "predictmatchoutcome",
    "calculatebetvalue",
    "comparemarketodds",
    "kellycriterion",
    "fetchlivematch",
    "fetchliveodds",
    "searchfixture",
    "searchleague",
    "graph_store_triple",
    "graph_search_neighbors",
]


@tool("คำสั่งทดสอบที่มีความเสี่ยงสูง (HITL)", risk_level="high")
async def test_high_risk_action(reason: str) -> str:
    """ใช้สำหรับทดสอบระบบ Human-in-the-Loop เท่านั้น"""
    return f"ดำเนินการ '{reason}' สำเร็จหลังจากได้รับอนุมัติ"


def make_default_registry() -> SeahorseToolRegistry:
    """Return a SeahorseToolRegistry pre-loaded with all built-in tools."""
    registry = SeahorseToolRegistry()
    for fn in (
        test_high_risk_action,
        execute_auto_seahorse,
        web_search,
        python_interpreter,
        list_files,
        read_file,
        write_file,
        memory_store,
        memory_search,
        memory_feedback,
        memory_delete,
        memory_clear,
        browser_scan,
        browser_scrape,
        browser_screenshot,
        browser_close,
        competitor_radar,
        war_room,
        auto_architect,
        slack_send_message,
        google_calendar_add_event,
        database_query,
        database_schema,
        calculate_promo_impact,
        calculate_margin,
        create_custom_chart,
        create_table_image,
        forecast_sales,
        polars_query,
        polars_profile,
        polars_inspect_join,
        convert_to_parquet,
        duckdb_sql,
        sql_to_polars,
        geth2hresults,
        getmatchintel,
        getupcomingfixtures,
        predictmatchoutcome,
        calculatebetvalue,
        comparemarketodds,
        kellycriterion,
        fetchlivematch,
        fetchliveodds,
        searchfixture,
        searchleague,
        graph_store_triple,
        graph_search_neighbors,
    ):
        registry.register(fn)
    return registry
