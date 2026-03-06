"""seahorse_ai.planner — ReAct (Reason + Act) agent planning loop.

Architecture
------------
ReActPlanner
  ├── _run_step()       — one LLM call + optional tool dispatch
  ├── _parse_answer()   — extract full Answer content (multi-line safe)
  ├── _parse_action()   — extract Action line
  ├── _execute_action() — call tool, return Observation string
  └── _needs_nudge()    — detect time-sensitive queries that skipped tools

Prompt templates and keyword lists live in `prompts.py`.
Tracing lives in `observability.py`.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Protocol, runtime_checkable

from seahorse_ai.observability import get_tracer, setup_telemetry
from seahorse_ai.prompts import REALTIME_KEYWORDS, REALTIME_NUDGE, build_system_prompt
from seahorse_ai.schemas import AgentRequest, AgentResponse, Message

logger = logging.getLogger(__name__)


# ── Protocols ─────────────────────────────────────────────────────────────────

@runtime_checkable
class LLMBackend(Protocol):
    """Any object that can complete a list of messages."""

    async def complete(self, messages: list[Message]) -> str: ...


@runtime_checkable
class ToolRegistry(Protocol):
    """Any object that can dispatch a named tool call."""

    async def call(self, name: str, args: dict[str, object]) -> str: ...


# ── Planner ───────────────────────────────────────────────────────────────────

class ReActPlanner:
    """Execute an agent reasoning loop up to `max_steps` iterations using native tool calling.

    Each iteration:
    1. Ask the LLM what to do next, providing available tools.
    2. If it emits `tool_calls` → execute the tools, append Observations.
    3. If it emits `content` and no tool calls → return immediately.
    """

    def __init__(
        self,
        llm: LLMBackend,
        tools: ToolRegistry | None = None,
        max_steps: int = 10,
    ) -> None:
        self._llm = llm
        self._tools = tools or self._default_tools()
        self._max_steps = max_steps
        self._tool_errors: dict[str, int] = {}
        setup_telemetry()  # idempotent

    # ── public ────────────────────────────────────────────────────────────────

    async def run(self, request: AgentRequest) -> AgentResponse:
        """Execute the native tool-calling loop and return the final response."""
        tracer = get_tracer("seahorse.planner")
        wall_start = time.monotonic()

        with tracer.start_as_current_span("agent.run") as span:
            self._set_span_attrs(span, {
                "agent.id": request.agent_id,
                "agent.prompt_len": len(request.prompt),
                "agent.max_steps": self._max_steps,
            })

            messages: list[Message] = [
                Message(role="system", content=build_system_prompt()),
            ]

            # 1) Append conversation history
            if request.history:
                messages.extend(request.history)

            # 2) Check if user prompt needs a real-time nudge
            prompt_content = request.prompt
            if self._needs_nudge(request.prompt):
                logger.info("agent.run nudging for real-time data")
                prompt_content = f"{prompt_content}\n\n{REALTIME_NUDGE}"

            messages.append(Message(role="user", content=prompt_content))

            logger.info(
                "agent.run start agent_id=%s max_steps=%d prompt_len=%d",
                request.agent_id, self._max_steps, len(request.prompt),
            )

            # Pre-compute the OpenAI tool definitions
            openai_tools = getattr(self._tools, "to_openai_tools", lambda: [])()

            for step in range(self._max_steps):
                response_msg, step_ms = await self._run_step(messages, openai_tools, step)
                
                # Append the assistant's raw message
                messages.append(Message(**response_msg))

                logger.debug("step=%d ms=%d preview=%r", step, step_ms, str(response_msg)[:100])

                tool_calls = response_msg.get("tool_calls")
                content = response_msg.get("content")

                # 1. Action: call tools natively (in parallel)
                if tool_calls:
                    # Create tasks for all tool calls
                    tasks = []
                    for tool_call in tool_calls:
                        func_call = tool_call.get("function", {})
                        action_name = func_call.get("name")
                        action_args_str = func_call.get("arguments", "{}")
                        call_id = tool_call.get("id")

                        tasks.append(
                            self._execute_action(
                                action_name, action_args_str, step, tracer, call_id
                            )
                        )
                    
                    # Execute all tools concurrently
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    
                    # Append observations
                    for tool_call, result in zip(tool_calls, results, strict=False):
                        func_call = tool_call.get("function", {})
                        action_name = func_call.get("name")
                        call_id = tool_call.get("id")
                        
                        is_error = isinstance(result, Exception) or (
                            isinstance(result, str) and result.startswith("Error")
                        )
                        if is_error and action_name:
                            self._tool_errors[action_name] = self._tool_errors.get(action_name, 0) + 1
                            if self._tool_errors[action_name] >= 2:
                                logger.warning("Self-correction triggered for tool: %s", action_name)
                                result = (
                                    f"{result}\n\n[SYSTEM: You have failed to use this tool "
                                    "correctly 2+ times. Please STOP and re-evaluate your plan. "
                                    "Try a different tool or approach.]"
                                )

                        observation_str = (
                            str(result) if not isinstance(result, Exception) else f"Error: {result}"
                        )
                        
                        messages.append(Message(
                            role="tool", 
                            content=observation_str,
                            tool_call_id=call_id,
                            name=action_name,
                        ))
                    continue

                # 2. Terminal: Answer found (no tool_calls, only content)
                if content:
                    total_ms = int((time.monotonic() - wall_start) * 1000)
                    logger.info(
                        "agent.run done agent_id=%s steps=%d ms=%d",
                        request.agent_id, step + 1, total_ms,
                    )
                    self._set_span_attrs(span, {
                        "agent.steps_taken": step + 1,
                        "agent.total_ms": total_ms,
                        "agent.status": "done",
                    })
                    # 3) Before returning, trigger background memory summarization
                    asyncio.create_task(self._auto_summarize_memory(messages))
                    
                    return AgentResponse(
                        content=content,
                        steps=step + 1,
                        agent_id=request.agent_id,
                    )

            # Max steps reached
            logger.warning("agent.run max_steps agent_id=%s", request.agent_id)
            self._set_span_attrs(span, {"agent.status": "max_steps_reached"})
            
            # Still try to summarize what we found before failing
            asyncio.create_task(self._auto_summarize_memory(messages))

            return AgentResponse(
                content="[Agent reached the maximum number of reasoning steps]",
                steps=self._max_steps,
                agent_id=request.agent_id,
            )

    # ── memory ────────────────────────────────────────────────────────────────

    async def _auto_summarize_memory(self, messages: list[Message]) -> None:
        """Background task: Analyze the conversation, extract key facts, and store them."""
        # Only summarize if there's enough interaction
        if len(messages) < 4:
            return

        summary_prompt = (
            "You are a background memory worker. "
            "Analyze the conversation below and extract KEY FACTS, USER PREFERENCES, "
            "and IMPORTANT CONTEXT that should be remembered for future interactions. "
            "CRITICAL: Each fact MUST be independent and stored on its own line. "
            "Do NOT combine multiple unrelated facts (e.g., name and drink) into one line. "
            "Example of GOOD atomic facts:\n"
            "- The user's name is Kim.\n"
            "- The user's favorite drink is Thai Tea.\n"
            "Format as a list of independent, concise fact strings. "
            "If no new important facts are found, return 'NONE'.\n\n"
            "### Conversation History ###\n"
        )
        
        history_text = "\n".join([f"{m.role}: {m.content}" for m in messages if m.role != "system"])
        
        try:
            # We use the same LLM but with a specific instruction
            raw_summary = await self._llm.complete([
                Message(role="system", content=summary_prompt + history_text)
            ])
            
            if "NONE" in raw_summary.upper() or len(raw_summary.strip()) < 5:
                return

            # Force splitting by lines AND common conjunctions to ensure atomic facts
            facts: list[str] = []
            for line in raw_summary.split("\n"):
                line = line.strip("-* ").strip()
                if not line or len(line) < 3:
                    continue

                # Split by common conjunctions if line seems too long or grouped
                if (" and " in line or " และ " in line) and len(line) > 30:
                    parts = line.replace(" และ ", " and ").split(" and ")
                    facts.extend([p.strip(". ") for p in parts if len(p.strip()) > 3])
                else:
                    facts.append(line.strip(". "))

            logger.info("auto_summarize_memory: extracted facts: %s", facts)

            from seahorse_ai.tools.memory import memory_store
            for fact in facts:
                if fact:
                    await memory_store(fact)
                    
            logger.info("auto_summarize_memory: stored %d facts", len(facts))
            
        except Exception as exc: # noqa: BLE001
            logger.error("auto_summarize_memory failed: %s", exc)

    # ── private helpers ───────────────────────────────────────────────────────

    def _needs_nudge(self, prompt: str) -> bool:
        """Return True if the user asks about time-sensitive keywords."""
        text = prompt.lower()
        return any(kw.lower() in text for kw in REALTIME_KEYWORDS)

    async def _run_step(
        self, messages: list[Message], tools: list[dict], step: int
    ) -> tuple[dict, int]:
        """Call the LLM and return (response_message_dict, elapsed_ms)."""
        t0 = time.monotonic()
        response_msg = await self._llm.complete(messages, tools=tools)  # type: ignore[call-arg]
        return response_msg, int((time.monotonic() - t0) * 1000)

    async def _execute_action(
        self,
        tool_name: str | None,
        args_str: str,
        step: int,
        tracer: object,
        call_id: str | None = None,
    ) -> str:
        """Parse arguments, call tool, return Observation string."""
        if not tool_name:
            return "Error: Tool name missing from tool_call."
            
        try:
            args: dict[str, object] = json.loads(args_str) if args_str else {}
            logger.info("tool.call step=%d tool=%s", step, tool_name)

            with getattr(tracer, "start_as_current_span", lambda n: _nullctx())(
                f"tool.{tool_name}"
            ) as tool_span:
                self._set_span_attrs(tool_span, {
                    "tool.name": tool_name,
                    "tool.step": step,
                    "tool.args": args_str[:200],
                })
                result = await self._tools.call(tool_name, args)
                self._set_span_attrs(tool_span, {"tool.result_len": len(result)})

            logger.info("tool.result step=%d tool=%s len=%d", step, tool_name, len(result))
            return result

        except Exception as exc:  # noqa: BLE001
            logger.error("tool.error step=%d action=%s error=%s", step, tool_name, exc)
            return f"Error executing {tool_name}: {exc}"

    @staticmethod
    def _set_span_attrs(span: object, attrs: dict[str, object]) -> None:
        """Set span attributes, silently ignoring errors (OTel may be disabled)."""
        try:
            for k, v in attrs.items():
                span.set_attribute(k, v)  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _default_tools() -> ToolRegistry:
        from seahorse_ai.tools import make_default_registry
        return make_default_registry()


# ── Null context manager for when OTel is absent ─────────────────────────────

class _nullctx:
    """No-op context manager — used when tracer.start_as_current_span is unavailable."""
    def __enter__(self) -> _nullctx: return self
    def __exit__(self, *_: object) -> None: pass
    def set_attribute(self, *_: object) -> None: pass
