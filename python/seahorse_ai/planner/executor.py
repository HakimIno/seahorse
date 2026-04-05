"""seahorse_ai.planner.executor — Pure ReAct execution loop.

Single responsibility: run N steps of the Reason+Act loop.
No memory management, no strategy generation, no error tracking.
Those concerns are handled by their respective classes.

Architecture:
  ReActExecutor.run(messages, tools, config)
    → for step in range(max_steps):
        → LLM call
        → if tool_calls: execute in parallel, append observations
        → if content: return final answer
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import anyio

if TYPE_CHECKING:
    from seahorse_ai.core.schemas import Message

logger = logging.getLogger(__name__)


@dataclass
class ExecutorConfig:
    """Configuration for the ReAct execution loop."""

    max_steps: int = 15
    step_timeout_seconds: int = 180
    global_timeout_seconds: int = 600
    token_burn_warn_chars: int = 30_000
    token_burn_hard_chars: int = 50_000


@dataclass
class ExecutorResult:
    """Result of a ReAct execution loop."""

    content: str
    steps: int
    evidence: list[str] = field(default_factory=list)
    terminated: bool = False
    termination_reason: str | None = None
    total_ms: int = field(default=0)
    image_paths: list[str] | None = None


class ReActExecutor:
    """Execute the ReAct loop. Delegates error tracking to CircuitBreaker.

    Does NOT handle:
    - Memory summarization (→ MemoryRecorder)
    - Strategy generation (→ StrategyPlanner)
    - Intent classification (→ prompts.classify_intent)
    """

    def __init__(
        self,
        llm: object,
        tools: object,
        circuit_breaker: object,
        config: ExecutorConfig | None = None,
        step_callback: Callable[..., Any] | None = None,
    ) -> None:
        self._llm = llm
        self._tools = tools
        self._cb = circuit_breaker
        self._cfg = config or ExecutorConfig()
        self._step_callback = step_callback
        self._total_obs_chars: int = 0
        self._last_tool_signature: str | None = None
        self._consecutive_repeats: int = 0

    async def run(
        self,
        messages: list[Message],
        openai_tools: list[dict],
        agent_id: str | None = None,
    ) -> ExecutorResult:
        """Run the ReAct loop and return an ExecutorResult."""
        from seahorse_ai.core.schemas import Message as Msg

        wall_start = time.monotonic()
        self._total_obs_chars = 0
        image_paths = []
        evidence = []

        for step in range(self._cfg.max_steps):
            # Global timeout guard
            elapsed = time.monotonic() - wall_start
            if elapsed > self._cfg.global_timeout_seconds:
                return ExecutorResult(
                    content="[TERMINATED] Agent took too long. Stopping to prevent waste.",
                    steps=step,
                    terminated=True,
                    termination_reason="global_timeout",
                    total_ms=int(elapsed * 1000),
                )

            # Run one step
            try:
                with anyio.fail_after(self._cfg.step_timeout_seconds):
                    response_data, step_ms = await self._run_step(messages, openai_tools, step)
            except TimeoutError:
                logger.error("executor step=%d timed out", step)
                messages.append(
                    Msg(
                        role="user",
                        content=(
                            f"(Internal Error: Step {step} timed out after "
                            f"{self._cfg.step_timeout_seconds}s. "
                            "Try a faster approach or shorter response.)"
                        ),
                    )
                )
                await self._cb.record_error(None)  # type: ignore[union-attr]
                terminate, reason = self._cb.should_terminate()  # type: ignore[union-attr]
                if terminate:
                    return ExecutorResult(
                        content=reason,
                        steps=step,
                        terminated=True,
                        termination_reason="consecutive_timeouts",
                    )
                continue
            except Exception as exc:
                logger.error("executor step=%d failed: %s", step, exc)
                raise

            # Normalize to Message
            import msgspec

            if isinstance(response_data, str):
                response_msg = Msg(role="assistant", content=response_data)
            else:
                if "role" not in response_data:
                    response_data["role"] = "assistant"
                # Use msgspec.convert since Msg is a Struct
                response_msg = msgspec.convert(response_data, Msg)

            messages.append(response_msg)
            logger.debug("executor step=%d ms=%d", step, step_ms)

            tool_calls = response_msg.tool_calls
            content = response_msg.content

            # ── Tool calls ────────────────────────────────────────────────────
            if tool_calls:
                # Execute all tools concurrently using AnyIO TaskGroup
                results: list[Any] = [None] * len(tool_calls)

                async def _run_tool(idx: int, tc: dict, step=step, results=results):
                    try:
                        results[idx] = await self._execute_tool(tc, step, agent_id)
                    except Exception as e:
                        results[idx] = e

                async with anyio.create_task_group() as tg:
                    for i, tc in enumerate(tool_calls):
                        tg.start_soon(_run_tool, i, tc)

                found_crash = False
                any_success = False

                for tool_call, result in zip(tool_calls, results, strict=False):
                    func = tool_call.get("function", {})
                    tool_name = func.get("name")
                    call_id = tool_call.get("id")

                    # Loop Guard: Check if AI is repeating the exact same tool call
                    tool_sig = f"{tool_name}:{func.get('arguments', '')}"
                    if tool_sig == self._last_tool_signature:
                        self._consecutive_repeats += 1
                    else:
                        self._last_tool_signature = tool_sig
                        self._consecutive_repeats = 0

                    if self._consecutive_repeats >= 2:
                        logger.warning("executor: loop detected on tool=%s — forcing termination", tool_name)
                        return ExecutorResult(
                            content=f"[TERMINATED] Loop detected. The agent repeated '{tool_name}' too many times. Please check the data.",
                            steps=step + 1,
                            terminated=True,
                            termination_reason="infinite_loop",
                        )

                    is_error = isinstance(result, Exception) or (
                        isinstance(result, str) and result.startswith(("Error", "SYSTEM_CRASH"))
                    )
                    if "SYSTEM_CRASH" in str(result):
                        found_crash = True

                    if is_error:
                        await self._cb.record_error(tool_name)  # type: ignore[union-attr]
                        observation = self._cb.get_nudge(tool_name, str(result))  # type: ignore[union-attr]
                    else:
                        any_success = True
                        observation = self._clean_observation(str(result))
                        # NEW: Truncate massive observations to save tokens limit
                        if len(observation) > 4000:
                            observation = (
                                observation[:4000]
                                + "\n\n...[TRUNCATED: Output too long. Please act on the current data or use narrower search.]"
                            )
                        # NEW: Add successful observations to evidence for the Critic
                        evidence.append(f"Tool {tool_name} returned: {observation[:1000]}")

                    self._total_obs_chars += len(observation)

                    messages.append(
                        Msg(
                            role="tool",
                            content=observation,
                            tool_call_id=call_id,
                            name=tool_name,
                        )
                    )

                if any_success:
                    self._cb.record_success()  # type: ignore[union-attr]

                if found_crash:
                    return ExecutorResult(
                        content="[TERMINATED] Internal tool crash. Please report this bug.",
                        steps=step + 1,
                        terminated=True,
                        termination_reason="system_crash",
                    )

                terminate, reason = self._cb.should_terminate()  # type: ignore[union-attr]
                if terminate:
                    return ExecutorResult(
                        content=reason,
                        steps=step + 1,
                        terminated=True,
                        termination_reason="consecutive_errors",
                    )

                # Token burn guard
                if self._total_obs_chars > self._cfg.token_burn_hard_chars:
                    return ExecutorResult(
                        content=("[TERMINATED] Data limit (50k chars) reached. Summarizing now."),
                        steps=step + 1,
                        terminated=True,
                        termination_reason="token_burn",
                    )
                if self._total_obs_chars > self._cfg.token_burn_warn_chars:
                    messages.append(
                        Msg(
                            role="user",
                            content="(Internal Control: 30k+ chars gathered. "
                            "Stop researching. Synthesize now.)",
                        )
                    )

                if self._step_callback:
                    await self._step_callback(messages)

                continue

            # ── Final answer ──────────────────────────────────────────────────
            if content:
                total_ms = int((time.monotonic() - wall_start) * 1000)
                logger.info(
                    "executor done agent_id=%s steps=%d ms=%d",
                    agent_id,
                    step + 1,
                    total_ms,
                )
                return ExecutorResult(
                    content=content,
                    steps=step + 1,
                    evidence=evidence,
                    total_ms=total_ms,
                    image_paths=image_paths if image_paths else None,
                )

    # Max steps reached
        return ExecutorResult(
            content="[Agent reached maximum reasoning steps]",
            steps=self._cfg.max_steps,
            terminated=True,
            termination_reason="max_steps",
        )

    def _clean_observation(self, text: str) -> str:
        """Strip provider-specific noise (URLs, headers) from tool observations."""
        if not text:
            return text

        # Remove LiteLLM / Model Provider noise that often leaks into results
        noise_patterns = [
            "Provider List: https://docs.litellm.ai/docs/providers",
            "https://docs.litellm.ai/docs/providers",
            "LiteLLM completion()",
        ]
        cleaned = text
        for pattern in noise_patterns:
            cleaned = cleaned.replace(pattern, "")

        return cleaned.strip()

    # ── Private ────────────────────────────────────────────────────────────────

    async def _run_step(
        self, messages: list[Message], tools: list[dict], step: int
    ) -> tuple[dict, int]:
        t0 = time.monotonic()
        # Escalate tier after 3 steps
        tier = "thinker" if step >= 3 else "worker"
        result = await self._llm.complete(messages, tools=tools, tier=tier)  # type: ignore[union-attr]
        return result, int((time.monotonic() - t0) * 1000)

    async def _execute_tool(
        self,
        tool_call: dict,
        step: int,
        agent_id: str | None,
    ) -> str:
        """Execute a single tool call and return observation string."""
        func = tool_call.get("function", {})
        tool_name = func.get("name")
        args_str = func.get("arguments", "{}")

        if not tool_name:
            return "Error: Tool name missing from tool_call."

        try:
            args: dict = json.loads(args_str) if args_str else {}
            if agent_id and tool_name in ("memory_store", "memory_search", "memory_delete"):
                args["agent_id"] = agent_id

            logger.info("executor tool.call step=%d tool=%s", step, tool_name)
            result = await self._tools.call(tool_name, args, agent_id=agent_id)  # type: ignore[call-arg]
            logger.info("executor tool.result step=%d tool=%s len=%d", step, tool_name, len(result))
            return result

        except GeneratorExit:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("executor tool.error step=%d tool=%s: %s", step, tool_name, exc)
            return f"Error executing {tool_name}: {exc}"
