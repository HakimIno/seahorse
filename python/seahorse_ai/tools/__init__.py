"""seahorse_ai.tools — tool registry and built-in tools.

Exports
-------
SeahorseToolRegistry   : registry class
ToolSpec               : tool metadata model
tool                   : @tool decorator
make_default_registry  : returns a registry with all built-in tools registered
"""
from seahorse_ai.tools.auto_architect import auto_architect
from seahorse_ai.tools.base import SeahorseToolRegistry, ToolSpec, tool
from seahorse_ai.tools.browser import browser_scan
from seahorse_ai.tools.business_math import calculate_margin, calculate_promo_impact
from seahorse_ai.tools.forecaster import forecast_sales
from seahorse_ai.tools.competitor_radar import competitor_radar
from seahorse_ai.tools.db import database_query, database_schema
from seahorse_ai.tools.filesystem import list_files, read_file, write_file
from seahorse_ai.tools.integrations import google_calendar_add_event, slack_send_message
from seahorse_ai.tools.mcp_client import load_mcp_tools
from seahorse_ai.tools.memory import (
    memory_clear,
    memory_delete,
    memory_search,
    memory_store,
)
from seahorse_ai.tools.auto_seahorse import execute_auto_seahorse
from seahorse_ai.tools.python_interpreter import python_interpreter
from seahorse_ai.tools.strategy_engine import war_room
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
    "memory_delete",
    "memory_clear",
    "browser_scan",
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
    "forecast_sales",
    "execute_auto_seahorse",
]


def make_default_registry() -> SeahorseToolRegistry:
    """Return a SeahorseToolRegistry pre-loaded with all built-in tools."""
    registry = SeahorseToolRegistry()
    for fn in (
        execute_auto_seahorse,
        web_search,
        python_interpreter,
        list_files,
        read_file,
        write_file,
        memory_store,
        memory_search,
        memory_delete,
        memory_clear,
        browser_scan,
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
        forecast_sales,
    ):
        registry.register(fn)
    return registry
