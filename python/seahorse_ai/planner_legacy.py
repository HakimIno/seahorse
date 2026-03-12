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
from seahorse_ai.prompts import (
    MEMORY_NUDGE,
    REALTIME_NUDGE,
    STRATEGY_GENERATION_PROMPT,
    STRATEGY_NUDGE,
    build_system_prompt,
    classify_intent,
)
from seahorse_ai.schemas import AgentRequest, AgentResponse, Message

logger = logging.getLogger(__name__)


# ── Protocols ─────────────────────────────────────────────────────────────────


class LLMBackend(Protocol):
    """Any object that can complete a list of messages with tier support."""

    async def complete(
        self, messages: list[Message], tools: list[dict] | None = None, tier: str = "worker"
    ) -> str | dict[str, object]: ...


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
        max_steps: int = 15,
        default_tier: str = "worker",
        step_timeout_seconds: int = 30,
        global_timeout_seconds: int = 120,
    ) -> None:
        self._llm = llm
        self._tools = tools or self._default_tools()
        self._max_steps = max_steps
        self._default_tier = default_tier
        self._step_timeout_seconds = step_timeout_seconds
        self._global_timeout_seconds = global_timeout_seconds
        self._tool_errors: dict[str, int] = {}
        self._consecutive_errors = 0
        self._total_obs_chars = 0
        setup_telemetry()  # idempotent

    # ── public ────────────────────────────────────────────────────────────────

    async def run(self, request: AgentRequest) -> AgentResponse:
        """Execute the native tool-calling loop and return the final response."""
        tracer = get_tracer("seahorse.planner")
        wall_start = time.monotonic()

        with tracer.start_as_current_span("agent.run") as span:
            self._set_span_attrs(
                span,
                {
                    "agent.id": request.agent_id,
                    "agent.prompt_len": len(request.prompt),
                    "agent.max_steps": self._max_steps,
                },
            )

            messages: list[Message] = [
                Message(role="system", content=build_system_prompt()),
            ]

            # 1) Append conversation history
            if request.history:
                messages.extend(request.history)

            # 2) Classify intent with two-tier system (keyword → LLM fallback)
            intent = await classify_intent(request.prompt, self._llm)

            # Apply nudge based on refined intent
            prompt_content = request.prompt
            if intent == "PUBLIC_REALTIME":
                logger.info("agent.run nudging for real-time data (intent=%s)", intent)
                prompt_content = f"{prompt_content}\n\n{REALTIME_NUDGE}"
            elif intent in ("PRIVATE_MEMORY", "DATABASE"):
                logger.info("agent.run nudging for memory retrieval (intent=%s)", intent)
                prompt_content = f"{prompt_content}\n\n{MEMORY_NUDGE}"

            messages.append(Message(role="user", content=prompt_content))

            logger.info(
                "agent.run start agent_id=%s max_steps=%d prompt_len=%d",
                request.agent_id,
                self._max_steps,
                len(request.prompt),
            )

            current_tier = getattr(self._llm, "classify_intent", lambda p: self._default_tier)(
                request.prompt
            )
            if current_tier == "strategist":
                # Strategist is for final summaries, use Thinker for the intermediate steps
                current_tier = "thinker"

            # Pre-compute the OpenAI tool definitions
            openai_tools = getattr(self._tools, "to_openai_tools", lambda: [])()

            # 2. Generate Strategy Plan for complex intents
            if current_tier in ("thinker", "strategist"):
                strategy_plan = await self._generate_strategy_plan(request.prompt)
                messages.insert(
                    1, Message(role="system", content=f"{strategy_plan}\n\n{STRATEGY_NUDGE}")
                )

            for step in range(self._max_steps):
                # Check global timeout
                if time.monotonic() - wall_start > self._global_timeout_seconds:
                    logger.error(
                        "agent.run terminating due to global timeout (%ds)",
                        self._global_timeout_seconds,
                    )
                    return AgentResponse(
                        content="[TERMINATED] The agent took too long to complete the task. "
                        "I am stopping to prevent wasting resources.",
                        steps=step,
                        agent_id=request.agent_id,
                    )

                # Escalation logic:
                # - If worker: stay on worker unless it's taking too long (step >= 3)
                # - If thinker/strategist: use thinker for reasoning steps
                if current_tier == "worker":
                    tier = "thinker" if step >= 3 else "worker"
                else:
                    tier = "thinker"

                # Normalize response to a Message object
                try:
                    # Enforce per-step timeout
                    response_data, step_ms = await asyncio.wait_for(
                        self._run_step(messages, openai_tools, step, tier=tier),
                        timeout=self._step_timeout_seconds,
                    )
                except TimeoutError:
                    logger.error(
                        "agent.run step=%d timed out after %ds", step, self._step_timeout_seconds
                    )
                    messages.append(
                        Message(
                            role="user",
                            content=f"[SYSTEM: Your previous step took too long (> {self._step_timeout_seconds}s) and timed out. "
                            "Please provide a shorter, faster response or take a different action.]",
                        )
                    )
                    self._consecutive_errors += 1
                    if self._consecutive_errors >= 3:
                        logger.error("agent.run terminating due to multiple step timeouts")
                        return AgentResponse(
                            content="[TERMINATED] Multiple steps timed out. "
                            "I am stopping to prevent wasting resources.",
                            steps=step + 1,
                            agent_id=request.agent_id,
                        )
                    continue
                except Exception as exc:
                    logger.error("agent.run step=%d failed: %s", step, exc)
                    raise

                # Normalize response to a Message object
                if isinstance(response_data, str):
                    response_msg = Message(role="assistant", content=response_data)
                else:
                    # It's a dict (expected for tool calls)
                    if "role" not in response_data:
                        response_data["role"] = "assistant"
                    response_msg = Message(
                        **response_data  # type: ignore[arg-type]
                    )

                messages.append(response_msg)

                logger.debug(
                    "step=%d ms=%d preview=%r", step, step_ms, str(response_msg.content)[:100]
                )

                tool_calls = response_msg.tool_calls
                content = response_msg.content

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
                                action_name,
                                action_args_str,
                                step,
                                tracer,
                                call_id,
                                agent_id=request.agent_id,
                            )
                        )

                    # Execute all tools concurrently
                    results = await asyncio.gather(*tasks, return_exceptions=True)

                    found_system_crash = False
                    # Append observations
                    for tool_call, result in zip(tool_calls, results, strict=False):
                        func_call = tool_call.get("function", {})
                        action_name = func_call.get("name")
                        call_id = tool_call.get("id")

                        observation_str = (
                            str(result) if not isinstance(result, Exception) else f"Error: {result}"
                        )
                        self._total_obs_chars += len(observation_str)

                        is_error = isinstance(result, Exception) or (
                            isinstance(result, str)
                            and (result.startswith("Error") or result.startswith("SYSTEM_CRASH"))
                        )

                        if is_error:
                            self._consecutive_errors += 1
                            if "SYSTEM_CRASH" in observation_str:
                                found_system_crash = True
                        else:
                            # We don't reset here because multiple tools can run.
                            # We reset if we get content later or if any tool succeeds?
                            # Actually, let's reset if AT LEAST one tool succeeds in this batch.
                            self._consecutive_errors = 0

                        if is_error and action_name:
                            self._tool_errors[action_name] = (
                                self._tool_errors.get(action_name, 0) + 1
                            )
                            if self._tool_errors[action_name] >= 2:
                                logger.warning("Self-correction triggered: %s", action_name)
                                observation_str = (
                                    f"{observation_str}\n\n[SYSTEM: You have failed to use "
                                    "this tool correctly 2+ times. Please STOP and re-evaluate "
                                    "your plan. Try a different tool or approach.]"
                                )

                        messages.append(
                            Message(
                                role="tool",
                                content=observation_str,
                                tool_call_id=call_id,
                                name=action_name,
                            )
                        )

                    if found_system_crash:
                        logger.error("agent.run terminating due to SYSTEM_CRASH")
                        return AgentResponse(
                            content="[TERMINATED] An internal technical error occurred in a tool. "
                            "Please report this bug.",
                            steps=step + 1,
                            agent_id=request.agent_id,
                        )

                    if self._consecutive_errors >= 3:
                        logger.error("agent.run terminating due to too many consecutive errors")
                        return AgentResponse(
                            content="[TERMINATED] Too many consecutive tool errors. "
                            "I am stopping to prevent wasting tokens.",
                            steps=step + 1,
                            agent_id=request.agent_id,
                        )

                    # Token Burn Guard: Monitor context size
                    if self._total_obs_chars > 30000:
                        logger.warning("Token Burn Guard: context size > 30k. Nudging synthesis.")
                        messages.append(
                            Message(
                                role="user",
                                content="[SYSTEM: You have gathered 30,000+ characters of data. "
                                "This is enough. Please STOP researching and synthesize "
                                "your final answer now.]",
                            )
                        )

                    if self._total_obs_chars > 50000:
                        logger.error("Token Burn Guard: hard limit reached (50k). Terminating.")
                        return AgentResponse(
                            content="[TERMINATED] Information limit reached (50k chars). "
                            "To prevent excessive costs, I am summarizing now.",
                            steps=step + 1,
                            agent_id=request.agent_id,
                        )

                    continue

                if content:
                    total_ms = int((time.monotonic() - wall_start) * 1000)
                    logger.info(
                        "agent.run done agent_id=%s steps=%d ms=%d",
                        request.agent_id,
                        step + 1,
                        total_ms,
                    )
                    self._set_span_attrs(
                        span,
                        {
                            "agent.steps_taken": step + 1,
                            "agent.total_ms": total_ms,
                            "agent.status": "done",
                        },
                    )
                    # 3) Before returning, trigger background memory summarization
                    asyncio.create_task(
                        self._auto_summarize_memory(messages, agent_id=request.agent_id)
                    )

                    # Final synthesis tier
                    final_tier = getattr(self._llm, "classify_intent", lambda p: "strategist")(
                        request.prompt
                    )
                    if final_tier == "strategist":
                        logger.info("Synthesizing final response with strategist model")
                        synth_msgs = messages + [Message(role="assistant", content=content)]
                        synth_msgs.append(
                            Message(role="user", content="สรุปคำตอบให้เป็นภาษากลยุทธ์ทางธุรกิจที่น่าสนใจ")
                        )
                        response_data = await self._llm.complete(synth_msgs, tier="strategist")
                        if isinstance(response_data, dict):
                            content = str(response_data.get("content", content))
                        else:
                            content = str(response_data)

                    return AgentResponse(
                        content=content,
                        steps=step + 1,
                        agent_id=request.agent_id,
                    )

            # Max steps reached
            logger.warning("agent.run max_steps agent_id=%s", request.agent_id)
            self._set_span_attrs(span, {"agent.status": "max_steps_reached"})

            # Still try to summarize what we found before failing
            asyncio.create_task(self._auto_summarize_memory(messages, agent_id=request.agent_id))

            return AgentResponse(
                content="[Agent reached the maximum number of reasoning steps]",
                steps=self._max_steps,
                agent_id=request.agent_id,
            )

    # ── memory ────────────────────────────────────────────────────────────────

    async def _auto_summarize_memory(
        self, messages: list[Message], agent_id: str | None = None
    ) -> None:
        """Background task: Analyze the conversation, extract key facts, and store them."""
        # Lowered threshold to ensure even brief interactions are captured
        if len(messages) < 2:
            return

        summary_prompt = (
            "You are a background memory worker. "
            "Analyze the conversation below and extract KEY FACTS, USER PREFERENCES, "
            "and IMPORTANT CONTEXT that should be remembered for future interactions. "
            "CRITICAL: Each fact MUST be independent. "
            "For each fact, assign an 'importance' level from 1 to 5: "
            "5 = Critical/Permanent (e.g. name, birthday), "
            "3 = Standard preference (e.g. food, hobbies), "
            "1 = Contextual/Temporary (e.g. today's plan). "
            "Format each fact as: [importance] Fact text. "
            "Example:\n"
            "- [5] The user's name is Kim.\n"
            "- [3] The user likes Thai Tea.\n"
            "If no new facts are found, return 'NONE'.\n\n"
            "### Conversation History ###\n"
        )

        history_text = "\n".join([f"{m.role}: {m.content}" for m in messages if m.role != "system"])

        try:
            response_data = await self._llm.complete(
                [Message(role="system", content=summary_prompt + history_text)]
            )

            # Normalize response to a string if it's a dict (expected from LLMClient)
            if isinstance(response_data, dict):
                raw_summary = str(response_data.get("content", ""))
            else:
                raw_summary = str(response_data)

            if "NONE" in raw_summary.upper() or len(raw_summary.strip()) < 5:
                return

            # Parse lines like "[3] Fact text"
            for line in raw_summary.split("\n"):
                line = line.strip("-* ").strip()
                if not line or len(line) < 5:
                    continue

                importance = 3  # Default
                fact_text = line

                # Check for [N] pattern
                if line.startswith("[") and "]" in line[:5]:
                    try:
                        imp_str = line[1 : line.index("]")]
                        importance = int(imp_str)
                        fact_text = line[line.index("]") + 1 :].strip()
                    except (ValueError, IndexError):
                        pass

                # Force splitting by common conjunctions
                split_markers = [" และ ", " and ", " ทั้งยัง ", " รวมถึง "]
                if any(m in fact_text for m in split_markers) and len(fact_text) > 30:
                    temp = fact_text
                    for m in split_markers:
                        temp = temp.replace(m, "SPLIT_TOKEN")
                    parts = [p.strip() for p in temp.split("SPLIT_TOKEN") if len(p.strip()) > 3]
                    for p in parts:
                        await self._tools.call(
                            "memory_store",
                            {"text": p, "importance": importance, "agent_id": agent_id},
                        )
                else:
                    await self._tools.call(
                        "memory_store",
                        {"text": fact_text, "importance": importance, "agent_id": agent_id},
                    )

            logger.info("auto_summarize_memory: processed background facts")

        except Exception as exc:  # noqa: BLE001
            logger.error("auto_summarize_memory failed: %s", exc)

    # ── private helpers ───────────────────────────────────────────────────────

    def _needs_nudge(self, prompt: str, keywords: tuple[str, ...]) -> bool:
        """Return True if the user prompt contains any of the given keywords."""
        p = prompt.lower()
        return any(k.lower() in p for k in keywords)

    async def _generate_strategy_plan(self, prompt: str) -> str:
        """Call high-tier model to create a master plan before execution."""
        messages = [
            Message(role="system", content=STRATEGY_GENERATION_PROMPT),
            Message(role="user", content=prompt),
        ]
        try:
            # Use 'thinker' tier for strategy generation
            # ReActPlanner uses self._llm (LLMBackend) which has a 'complete' method
            plan = await self._llm.complete(messages, tier="thinker")
            logger.info("Strategy Plan generated.")
            return str(plan)
        except Exception as exc:
            logger.error("Failed to generate strategy plan: %s", exc)
            return "[STRATEGY PLAN] Proceed with standard ReAct loop."

    async def _run_step(
        self, messages: list[Message], tools: list[dict], step: int, tier: str = "worker"
    ) -> tuple[dict, int]:
        """Call the LLM and return (response_message_dict, elapsed_ms)."""
        t0 = time.monotonic()
        response_msg = await self._llm.complete(messages, tools=tools, tier=tier)  # type: ignore[call-arg]
        return response_msg, int((time.monotonic() - t0) * 1000)

    async def _execute_action(
        self,
        tool_name: str | None,
        args_str: str,
        step: int,
        tracer: object,
        call_id: str | None = None,
        agent_id: str | None = None,
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
                self._set_span_attrs(
                    tool_span,
                    {
                        "tool.name": tool_name,
                        "tool.step": step,
                        "tool.args": args_str[:200],
                    },
                )
                # We do this by checking if the registry can inject it or just adding it to args.
                if agent_id and tool_name in ["memory_store", "memory_search", "memory_delete"]:
                    args["agent_id"] = agent_id

                result = await self._tools.call(tool_name, args)
                self._set_span_attrs(tool_span, {"tool.result_len": len(result)})

            logger.info("tool.result step=%d tool=%s len=%d", step, tool_name, len(result))
            return result

        except GeneratorExit:
            # Task was cancelled, just re-raise
            raise
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

    def __enter__(self) -> _nullctx:
        return self

    def __exit__(self, *_: object) -> None:
        pass

    def set_attribute(self, *_: object) -> None:
        pass
