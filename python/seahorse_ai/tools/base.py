from __future__ import annotations

import inspect
import logging
from collections.abc import Callable
from typing import Any, TypeVar

import anyio
from msgspec import Struct

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


class ToolSpec(Struct):
    """Metadata for a registered tool."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema subset
    risk_level: str = "low"


def tool(description: str, risk_level: str = "low") -> Callable[[F], F]:
    """Decorator that marks a function as a Seahorse Agent tool.

    Usage::

        @tool("Search the web for real-time information")
        async def web_search(query: str) -> str:
            ...
            
        @tool("Execute financial trade", risk_level="high")
        async def execute_trade(amount: int) -> str:
            ...
    """

    def decorator(fn: F) -> F:
        fn._tool_spec = ToolSpec(  # type: ignore[attr-defined]
            name=fn.__name__,
            description=description,
            parameters=_json_schema_from_fn(fn),
            risk_level=risk_level,
        )
        return fn

    return decorator


class ToolError(Exception):
    """Base class for tool-related errors."""

    def __init__(self, message: str, is_system_error: bool = False) -> None:
        super().__init__(message)
        self.is_system_error = is_system_error


class ToolInputError(ToolError):
    """Error caused by invalid model inputs/arguments."""

    def __init__(self, message: str) -> None:
        super().__init__(message, is_system_error=False)


class ToolSystemError(ToolError):
    """Error caused by internal code bugs or environment issues."""

    def __init__(self, message: str) -> None:
        super().__init__(message, is_system_error=True)


class SeahorseToolRegistry:
    """Registry that stores tools and dispatches calls by name."""

    def __init__(self) -> None:
        self._tools: dict[str, tuple[Callable[..., Any], ToolSpec]] = {}

    def register(self, fn: Callable[..., Any]) -> None:
        """Register a function decorated with @tool."""
        spec: ToolSpec = getattr(fn, "_tool_spec", None)  # type: ignore[assignment]
        if spec is None:
            raise ValueError(f"{fn.__name__} is not decorated with @tool")
        self._tools[spec.name] = (fn, spec)
        logger.debug("registered tool: %s", spec.name)

    def to_openai_tools(self) -> list[dict[str, Any]]:
        """Return the LiteLLM / OpenAI formatted tool definitions."""
        return [
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.parameters,
                },
            }
            for spec in self.specs
        ]

    async def call(self, name: str, args: dict[str, object], agent_id: str | None = None) -> str:
        """Call a tool by name with the given arguments."""
        if name not in self._tools:
            return f"Error: unknown tool '{name}'. Available: {list(self._tools)}"
        fn, spec = self._tools[name]
        
        if spec.risk_level == "high":
            from seahorse_ai.hitl import approval_manager
            logger.warning("Tool '%s' is marked as high-risk. Requesting approval...", name)
            
            # Use provided agent_id, or try to extract from args
            effective_agent_id = agent_id or args.get("agent_id")
            
            approved = await approval_manager.request_approval(name, args, effective_agent_id)
            if not approved:
                logger.info("Human rejected execution of '%s'", name)
                return "ERROR: Action rejected by human overseer. Do not attempt this action again without permission."

        try:
            if inspect.iscoroutinefunction(fn):
                result = await fn(**args)
            else:
                # Run synchronous tools (like matplotlib) in a thread pool
                # to prevent blocking the main event loop
                result = await anyio.to_thread.run_sync(lambda: fn(**args))

            return str(result)
        except TypeError as exc:
            # TypeErrors are usually internal code bugs (like the slice error)
            # OR missing required arguments (which should be caught by schema, but just in case)
            logger.error("tool '%s' system error: %s", name, exc)
            return f"SYSTEM_CRASH: Internal error in {name}. {exc}"
        except Exception as exc:  # noqa: BLE001
            # Check if it looks like a system error
            is_system = isinstance(exc, (RuntimeError, NameError, AttributeError, ImportError))
            prefix = "SYSTEM_CRASH:" if is_system else "Error:"
            logger.error("tool '%s' raised %s: %s", name, type(exc).__name__, exc)
            return f"{prefix} calling {name}: {exc}"

    @property
    def specs(self) -> list[ToolSpec]:
        """All registered tool specs."""
        return [spec for _, spec in self._tools.values()]

    def __repr__(self) -> str:
        return f"SeahorseToolRegistry(tools={list(self._tools)})"


def _json_schema_from_fn(fn: Callable[..., Any]) -> dict[str, Any]:
    """Extract a minimal JSON schema from function type hints."""
    sig = inspect.signature(fn)
    properties: dict[str, dict[str, str]] = {}
    required: list[str] = []

    _type_map = {str: "string", int: "integer", float: "number", bool: "boolean"}

    for name, param in sig.parameters.items():
        if name == "self":
            continue
        ann = param.annotation
        json_type = _type_map.get(ann, "string")
        properties[name] = {"type": json_type}
        if param.default is inspect.Parameter.empty:
            required.append(name)

    return {"type": "object", "properties": properties, "required": required}
