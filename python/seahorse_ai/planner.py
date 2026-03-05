"""ReAct (Reason + Act) planning loop for Seahorse Agent."""
from __future__ import annotations

import json
import logging
from typing import Protocol, runtime_checkable

from seahorse_ai.schemas import AgentRequest, AgentResponse, Message

logger = logging.getLogger(__name__)

REACT_SYSTEM_PROMPT = """\
You are Seahorse Agent — a high-performance AI agent.
Respond using the ReAct format:

Thought: reason step-by-step about what to do next
Action: tool_name({"arg": "value"})  ← call a tool
Observation: [tool result is inserted here]
... repeat Thought/Action/Observation as needed ...
Answer: your final answer to the user

Rules:
- Always begin with Thought.
- Use Action ONLY when you need a tool.
- Answer MUST start with "Answer:" when you have the final response.
- Do NOT fabricate Observations — they come from real tool calls.
"""


@runtime_checkable
class LLMBackend(Protocol):
    """Protocol so ReActPlanner accepts any LLM implementation."""

    async def complete(self, messages: list[Message]) -> str:
        ...


@runtime_checkable
class ToolRegistry(Protocol):
    """Protocol for the tool registry passed to ReActPlanner."""

    async def call(self, name: str, args: dict[str, object]) -> str:
        ...


class ReActPlanner:
    """Runs a ReAct reasoning loop up to `max_steps` iterations."""

    def __init__(
        self,
        llm: LLMBackend,
        tools: ToolRegistry,
        max_steps: int = 10,
    ) -> None:
        self._llm = llm
        self._tools = tools
        self._max_steps = max_steps

    async def run(self, request: AgentRequest) -> AgentResponse:
        """Execute the full ReAct loop and return the final response."""
        messages: list[Message] = [
            Message(role="system", content=REACT_SYSTEM_PROMPT),
            Message(role="user", content=request.prompt),
        ]

        for step in range(self._max_steps):
            response_text = await self._llm.complete(messages)
            messages.append(Message(role="assistant", content=response_text))

            logger.debug("step=%d response=%s", step, response_text[:120])

            # Terminal condition
            for line in response_text.splitlines():
                if line.startswith("Answer:"):
                    return AgentResponse(
                        content=line.removeprefix("Answer:").strip(),
                        steps=step + 1,
                        agent_id=request.agent_id,
                    )

            # Execute tool if Action present
            action_line = next(
                (line for line in response_text.splitlines() if line.startswith("Action:")),
                None,
            )
            if action_line:
                observation = await self._execute_action(action_line)
                messages.append(Message(role="user", content=f"Observation: {observation}"))

        logger.warning("max_steps=%d reached for agent_id=%s", self._max_steps, request.agent_id)
        return AgentResponse(
            content="[Agent reached maximum reasoning steps without a final answer]",
            steps=self._max_steps,
            agent_id=request.agent_id,
        )

    async def _execute_action(self, action_line: str) -> str:
        """Parse and execute an Action line, returning the Observation string."""
        raw = action_line.removeprefix("Action:").strip()
        try:
            tool_name, _, rest = raw.partition("(")
            args_str = rest.rstrip(")")
            args: dict[str, object] = json.loads(args_str) if args_str else {}
            return await self._tools.call(tool_name.strip(), args)
        except Exception as exc:  # noqa: BLE001
            logger.error("tool call failed: %s", exc)
            return f"Error: {exc}"
