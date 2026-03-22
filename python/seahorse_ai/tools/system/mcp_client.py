"""seahorse_ai.tools.system.mcp_client — Model Context Protocol (MCP) integration.

Allows Seahorse agents to dynamically connect to MCP servers (via stdio)
and interact with tools hosted remotely without writing custom integrations.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from seahorse_ai.tools.base import SeahorseToolRegistry, ToolSpec

logger = logging.getLogger(__name__)


async def load_mcp_session(
    server_command: str, server_args: list[str]
) -> tuple[ClientSession, AsyncExitStack]:
    """Connect to an MCP server over stdio and return the active session."""
    server_params = StdioServerParameters(command=server_command, args=server_args)

    stack = AsyncExitStack()

    # Enter stdio_client
    client_ctx = stdio_client(server_params)
    read, write = await stack.enter_async_context(client_ctx)

    # Enter ClientSession
    session_ctx = ClientSession(read, write)
    session = await stack.enter_async_context(session_ctx)

    await session.initialize()
    logger.info("Initialized MCP session with %s %s", server_command, server_args)
    return session, stack


def _create_mcp_tool_wrapper(session: ClientSession, mcp_tool_name: str) -> Callable:
    """Creates an async function that forwards calls to the MCP server."""

    async def wrapper(**kwargs: Any) -> str:
        logger.info("Calling MCP tool: %s", mcp_tool_name)
        result = await session.call_tool(mcp_tool_name, kwargs)

        # Format the result correctly based on mcp standard
        if not result or not hasattr(result, "content"):
            return str(result)

        texts = [c.text for c in result.content if getattr(c, "type", "") == "text"]
        if result.isError:
            return f"[ERROR] MCP Tool {mcp_tool_name} returned an error:\n" + "\n".join(texts)
        return "\n".join(texts)

    wrapper.__name__ = f"mcp_{mcp_tool_name}"
    return wrapper


async def load_mcp_tools(
    registry: SeahorseToolRegistry, server_command: str, server_args: list[str]
) -> tuple[ClientSession, AsyncExitStack]:
    """Connects to server, queries available tools, and registers them dynamically."""
    session, stack = await load_mcp_session(server_command, server_args)

    response = await session.list_tools()

    for mcp_tool in response.tools:
        # Construct parameters from json schema
        params_schema = getattr(mcp_tool, "inputSchema", {})

        # Build ToolSpec
        spec = ToolSpec(
            name=f"mcp_{mcp_tool.name}",
            description=mcp_tool.description or f"MCP tool: {mcp_tool.name}",
            parameters=params_schema,
        )

        # Create function wrapper
        func = _create_mcp_tool_wrapper(session, mcp_tool.name)
        func.__doc__ = spec.description

        # Store metadata directly onto the function so `ToolRegistry.register` can read it
        func._tool_spec = spec

        registry.register(func)
        logger.info("Registered MCP tool: %s", spec.name)

    return session, stack
