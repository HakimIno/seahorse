"""seahorse_ai.tools — tool registry and built-in tools.

Exports
-------
SeahorseToolRegistry   : registry class
ToolSpec               : tool metadata model
tool                   : @tool decorator
make_default_registry  : returns a registry with all built-in tools registered
"""
from seahorse_ai.tools.base import SeahorseToolRegistry, ToolSpec, tool
from seahorse_ai.tools.browser import browser_scan
from seahorse_ai.tools.filesystem import list_files, read_file, write_file
from seahorse_ai.tools.integrations import google_calendar_add_event, slack_send_message
from seahorse_ai.tools.memory import (
    memory_clear,
    memory_delete,
    memory_search,
    memory_store,
)
from seahorse_ai.tools.python_interpreter import python_interpreter
from seahorse_ai.tools.web_search import web_search

__all__ = [
    "SeahorseToolRegistry",
    "ToolSpec",
    "tool",
    "make_default_registry",
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
    "slack_send_message",
    "google_calendar_add_event",
]


def make_default_registry() -> SeahorseToolRegistry:
    """Return a SeahorseToolRegistry pre-loaded with all built-in tools."""
    registry = SeahorseToolRegistry()
    for fn in (
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
        slack_send_message,
        google_calendar_add_event,
    ):
        registry.register(fn)
    return registry
