from __future__ import annotations

from typing import TYPE_CHECKING, Any

from seahorse_ai.schemas import AgentResponse, Message

if TYPE_CHECKING:
    from seahorse_ai.router import ModelRouter
    from seahorse_ai.tools.base import ToolRegistry

class BaseFastHandler:
    """Base category handler for FastPathRouter logic."""
    
    def __init__(self, llm: ModelRouter, tools: ToolRegistry):
        self._llm = llm
        self._tools = tools

    async def handle(self, prompt: str, history: list[Message] | None, start_t: float, **kwargs: Any) -> AgentResponse | None:
        """Process the request. Returns AgentResponse if handled, None otherwise."""
        raise NotImplementedError("Subclasses must implement handle()")
