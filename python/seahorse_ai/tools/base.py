"""Tool base — @tool decorator and ToolRegistry."""
from __future__ import annotations

import inspect
import logging
from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import BaseModel

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


class ToolSpec(BaseModel):
    """Metadata for a registered tool."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema subset


def tool(description: str) -> Callable[[F], F]:
    """Decorator that marks a function as a Seahorse Agent tool.

    Usage::

        @tool("Search the web for real-time information")
        async def web_search(query: str) -> str:
            ...
    """

    def decorator(fn: F) -> F:
        fn._tool_spec = ToolSpec(  # type: ignore[attr-defined]
            name=fn.__name__,
            description=description,
            parameters=_json_schema_from_fn(fn),
        )
        return fn

    return decorator


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

    async def call(self, name: str, args: dict[str, object]) -> str:
        """Call a tool by name with the given arguments."""
        if name not in self._tools:
            return f"Error: unknown tool '{name}'. Available: {list(self._tools)}"
        fn, _ = self._tools[name]
        try:
            result = fn(**args)
            if inspect.isawaitable(result):
                result = await result
            return str(result)
        except Exception as exc:  # noqa: BLE001
            logger.error("tool '%s' raised: %s", name, exc)
            return f"Error calling {name}: {exc}"

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
