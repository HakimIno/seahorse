"""seahorse_ai.tools — tool registry and built-in tools.

Exports
-------
SeahorseToolRegistry   : registry class
ToolSpec               : tool metadata model
tool                   : @tool decorator
make_default_registry  : returns a registry with all built-in tools registered
"""

from seahorse_ai.tools.internal.auto_architect import auto_architect
from seahorse_ai.tools.internal.auto_seahorse import execute_auto_seahorse
from seahorse_ai.tools.base import SeahorseToolRegistry, ToolSpec, tool
from seahorse_ai.tools.system.browser import (
    browser_close,
    browser_scan,
    browser_scrape,
    browser_screenshot,
)
from seahorse_ai.tools.data.data_connectors import extract_sql_to_parquet, load_to_sql
from seahorse_ai.tools.data.data_profiler import data_profile
from seahorse_ai.tools.visual.echarts_composer import echarts_composer
from seahorse_ai.tools.visual.echarts_viz import native_echarts_chart
from seahorse_ai.tools.business.competitor_radar import competitor_radar
from seahorse_ai.tools.data.db import database_query, database_schema
from seahorse_ai.tools.data.duckdb_analyst import duckdb_query_json, duckdb_sql, sql_to_polars
from seahorse_ai.tools.system.filesystem import list_files, read_file, write_file
from seahorse_ai.tools.internal.graph_memory import (
    graph_search_neighbors,
    graph_store_triple,
)
from seahorse_ai.tools.business.financial_engine import (
    calculate_break_even,
    calculate_margin,
    calculate_promo_impact,
    scenario_analysis,
)
from seahorse_ai.tools.business.forecaster import forecast_sales
from seahorse_ai.tools.system.integrations import (
    google_calendar_add_event,
    slack_send_message,
)
from seahorse_ai.tools.system.mcp_client import load_mcp_tools
from seahorse_ai.tools.internal.memory import (
    memory_clear,
    memory_delete,
    memory_feedback,
    memory_search,
    memory_store,
)
from seahorse_ai.tools.data.polars_analyst import (
    convert_to_parquet,
    native_polars_aggregate,
    polars_inspect_join,
    polars_profile,
    polars_query,
)
from seahorse_ai.tools.system.python_interpreter import python_interpreter
from seahorse_ai.tools.business.strategy_engine import war_room
from seahorse_ai.tools.visual.table_viz import create_table_image
from seahorse_ai.tools.visual.viz import create_custom_chart
from seahorse_ai.tools.system.web_search import web_search
from seahorse_ai.tools.trading.risk_calculator import calculate_position_size, calculate_risk_of_ruin, evaluate_kelly_criterion
from seahorse_ai.tools.trading.market_data import get_futures_live_price, get_futures_market_depth, get_stock_live_price, get_forex_live_price
from seahorse_ai.tools.trading.portfolio import get_ibkr_account_summary, get_ibkr_open_positions, place_ibkr_order
from seahorse_ai.tools.trading.macro_watch import fetch_cme_fedwatch_data, fetch_cot_report

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
    "calculate_break_even",
    "scenario_analysis",
    "create_custom_chart",
    "create_table_image",
    "forecast_sales",
    "execute_auto_seahorse",
    "polars_query",
    "polars_profile",
    "polars_inspect_join",
    "convert_to_parquet",
    "duckdb_sql",
    "duckdb_query_json",
    "sql_to_polars",
    "graph_store_triple",
    "graph_search_neighbors",
    "data_profile",
    "extract_sql_to_parquet",
    "load_to_sql",
    "echarts_composer",
    "calculate_position_size",
    "calculate_risk_of_ruin",
    "evaluate_kelly_criterion",
    "get_futures_live_price",
    "get_futures_market_depth",
    "get_stock_live_price",
    "get_forex_live_price",
    "get_ibkr_account_summary",
    "get_ibkr_open_positions",
    "place_ibkr_order",
    "fetch_cme_fedwatch_data",
    "fetch_cot_report",
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
        calculate_break_even,
        calculate_promo_impact,
        calculate_margin,
        scenario_analysis,
        create_custom_chart,
        create_table_image,
        forecast_sales,
        polars_query,
        polars_profile,
        polars_inspect_join,
        native_polars_aggregate,
        convert_to_parquet,
        duckdb_sql,
        duckdb_query_json,
        sql_to_polars,
        native_echarts_chart,
        graph_store_triple,
        graph_search_neighbors,
        data_profile,
        extract_sql_to_parquet,
        load_to_sql,
        echarts_composer,
        calculate_position_size,
        calculate_risk_of_ruin,
        evaluate_kelly_criterion,
        get_futures_live_price,
        get_futures_market_depth,
        get_stock_live_price,
        get_forex_live_price,
        get_ibkr_account_summary,
        get_ibkr_open_positions,
        place_ibkr_order,
        fetch_cme_fedwatch_data,
        fetch_cot_report,
    ):
        registry.register(fn)
    return registry
