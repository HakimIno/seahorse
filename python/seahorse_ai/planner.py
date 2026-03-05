"""ReAct (Reason + Act) planning loop for Seahorse Agent — with OTel tracing."""
from __future__ import annotations

import json
import logging
import time
from typing import Protocol, runtime_checkable

from seahorse_ai.observability import get_tracer, setup_telemetry, span
from seahorse_ai.schemas import AgentRequest, AgentResponse, Message

logger = logging.getLogger(__name__)

REACT_SYSTEM_PROMPT = """\
You are Seahorse Agent — a high-performance AI agent with long-term memory.
Respond using the ReAct format:

Thought: reason step-by-step about what to do next
Action: tool_name({"arg": "value"})  ← call a tool
Observation: [tool result is inserted here]
... repeat Thought/Action/Observation as needed ...
Answer: your final answer to the user

Available tools:
- web_search({"query": "..."})        — search the web for up-to-date information
- python_interpreter({"code": "..."}) — run Python code for calculations/logic
- list_files({"path": "."})           — list files in the workspace
- read_file({"path": "..."})          — read a file from the workspace
- write_file({"path": "...", "content": "..."}) — write a file to the workspace
- memory_store({"text": "..."})       — save important information to long-term memory
- memory_search({"query": "...", "k": 5}) — retrieve relevant memories by semantic similarity

Rules:
- Always begin with Thought.
- Use memory_search FIRST if the question might have been discussed before.
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
        tools: ToolRegistry | None = None,
        max_steps: int = 10,
    ) -> None:
        self._llm = llm
        if tools is None:
            from seahorse_ai.tools import make_default_registry
            tools = make_default_registry()
        self._tools = tools
        self._max_steps = max_steps
        # Ensure OTel is configured (idempotent — no-op if already done)
        setup_telemetry()

    async def run(self, request: AgentRequest) -> AgentResponse:
        """Execute the full ReAct loop and return the final response."""
        tracer = get_tracer("seahorse.planner")
        start = time.monotonic()

        # Root span for the entire agent run
        with tracer.start_as_current_span("agent.run") as root_span:
            try:
                root_span.set_attribute("agent.id", request.agent_id)
                root_span.set_attribute("agent.prompt_len", len(request.prompt))
                root_span.set_attribute("agent.max_steps", self._max_steps)
            except Exception:  # noqa: BLE001
                pass

            messages: list[Message] = [
                Message(role="system", content=REACT_SYSTEM_PROMPT),
                Message(role="user", content=request.prompt),
            ]

            logger.info(
                "planner.run: agent_id=%s max_steps=%d prompt_len=%d",
                request.agent_id, self._max_steps, len(request.prompt),
            )

            for step in range(self._max_steps):
                step_start = time.monotonic()

                with tracer.start_as_current_span(f"agent.step.{step}") as step_span:
                    try:
                        step_span.set_attribute("agent.step", step)
                    except Exception:  # noqa: BLE001
                        pass

                    response_text = await self._llm.complete(messages)
                    step_ms = int((time.monotonic() - step_start) * 1000)
                    messages.append(Message(role="assistant", content=response_text))

                    logger.debug(
                        "planner step=%d elapsed_ms=%d response_preview=%s",
                        step, step_ms, response_text[:120],
                    )

                    # Terminal condition
                    for line in response_text.splitlines():
                        if line.startswith("Answer:"):
                            total_ms = int((time.monotonic() - start) * 1000)
                            logger.info(
                                "planner.done: agent_id=%s steps=%d total_ms=%d",
                                request.agent_id, step + 1, total_ms,
                            )
                            try:
                                root_span.set_attribute("agent.steps_taken", step + 1)
                                root_span.set_attribute("agent.total_ms", total_ms)
                                root_span.set_attribute("agent.status", "done")
                            except Exception:  # noqa: BLE001
                                pass
                            return AgentResponse(
                                content=line.removeprefix("Answer:").strip(),
                                steps=step + 1,
                                agent_id=request.agent_id,
                            )

                    # Execute tool if Action present
                    action_line = next(
                        (l for l in response_text.splitlines() if l.startswith("Action:")),
                        None,
                    )
                    if action_line:
                        observation = await self._execute_action(
                            action_line, step=step, tracer=tracer
                        )
                        messages.append(
                            Message(role="user", content=f"Observation: {observation}")
                        )

            logger.warning(
                "planner.max_steps_reached: agent_id=%s steps=%d",
                request.agent_id, self._max_steps,
            )
            try:
                root_span.set_attribute("agent.status", "max_steps_reached")
            except Exception:  # noqa: BLE001
                pass
            return AgentResponse(
                content="[Agent reached maximum reasoning steps without a final answer]",
                steps=self._max_steps,
                agent_id=request.agent_id,
            )

    async def _execute_action(
        self,
        action_line: str,
        step: int = 0,
        tracer: object | None = None,
    ) -> str:
        """Parse and execute an Action line, returning the Observation string."""
        raw = action_line.removeprefix("Action:").strip()
        try:
            tool_name, _, rest = raw.partition("(")
            args_str = rest.rstrip(")")
            args: dict[str, object] = json.loads(args_str) if args_str else {}
            tool_name = tool_name.strip()

            logger.info(
                "tool.call: step=%d tool=%s args_preview=%s",
                step, tool_name, args_str[:80],
            )

            span_name = f"tool.{tool_name}"
            if tracer is None:
                tracer = get_tracer("seahorse.tools")

            with tracer.start_as_current_span(span_name) as tool_span:
                try:
                    tool_span.set_attribute("tool.name", tool_name)
                    tool_span.set_attribute("tool.step", step)
                    tool_span.set_attribute("tool.args", args_str[:200])
                except Exception:  # noqa: BLE001
                    pass

                result = await self._tools.call(tool_name, args)

                try:
                    tool_span.set_attribute("tool.result_len", len(result))
                except Exception:  # noqa: BLE001
                    pass

            logger.info(
                "tool.result: step=%d tool=%s result_len=%d",
                step, tool_name, len(result),
            )
            return result

        except Exception as exc:  # noqa: BLE001
            logger.error("tool.error: step=%d action=%r error=%s", step, raw[:80], exc)
            return f"Error: {exc}"
