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

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from seahorse_ai.schemas import Message

logger = logging.getLogger(__name__)


@dataclass
class ExecutorConfig:
    """Configuration for the ReAct execution loop."""
    max_steps: int = 15
    step_timeout_seconds: int = 60
    global_timeout_seconds: int = 300
    token_burn_warn_chars: int = 30_000
    token_burn_hard_chars: int = 50_000


@dataclass
class ExecutorResult:
    """Result of a ReAct execution loop."""
    content: str
    steps: int
    terminated: bool = False
    termination_reason: str = ""
    total_ms: int = field(default=0)


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
    ) -> None:
        self._llm = llm
        self._tools = tools
        self._cb = circuit_breaker
        self._cfg = config or ExecutorConfig()
        self._total_obs_chars: int = 0

    async def run(
        self,
        messages: list[Message],
        openai_tools: list[dict],
        agent_id: str | None = None,
    ) -> ExecutorResult:
        """Run the ReAct loop and return an ExecutorResult."""
        from seahorse_ai.schemas import Message as Msg

        wall_start = time.monotonic()
        self._total_obs_chars = 0

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
                response_data, step_ms = await asyncio.wait_for(
                    self._run_step(messages, openai_tools, step),
                    timeout=self._cfg.step_timeout_seconds,
                )
            except TimeoutError:
                logger.error("executor step=%d timed out", step)
                messages.append(Msg(
                    role="user",
                    content=(
                        f"[SYSTEM: Step {step} timed out after "
                        f"{self._cfg.step_timeout_seconds}s. "
                        "Try a faster approach or shorter response.]"
                    ),
                ))
                self._cb.record_error(None)  # type: ignore[union-attr]
                terminate, reason = self._cb.should_terminate()  # type: ignore[union-attr]
                if terminate:
                    return ExecutorResult(
                        content=reason, steps=step, terminated=True,
                        termination_reason="consecutive_timeouts",
                    )
                continue
            except Exception as exc:
                logger.error("executor step=%d failed: %s", step, exc)
                raise

            # Normalize to Message
            if isinstance(response_data, str):
                response_msg = Msg(role="assistant", content=response_data)
            else:
                if "role" not in response_data:
                    response_data["role"] = "assistant"
                response_msg = Msg(**response_data)  # type: ignore[arg-type]

            messages.append(response_msg)
            logger.debug("executor step=%d ms=%d", step, step_ms)

            tool_calls = response_msg.tool_calls
            content = response_msg.content

            # ── Tool calls ────────────────────────────────────────────────────
            if tool_calls:
                # Execute all tools concurrently
                tasks = [
                    self._execute_tool(tc, step, agent_id)
                    for tc in tool_calls
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                found_crash = False
                any_success = False

                for tool_call, result in zip(tool_calls, results, strict=False):
                    func = tool_call.get("function", {})
                    tool_name = func.get("name")
                    call_id = tool_call.get("id")

                    is_error = isinstance(result, Exception) or (
                        isinstance(result, str) and result.startswith(("Error", "SYSTEM_CRASH"))
                    )
                    if "SYSTEM_CRASH" in str(result):
                        found_crash = True

                    if is_error:
                        self._cb.record_error(tool_name)  # type: ignore[union-attr]
                        observation = self._cb.get_nudge(tool_name, str(result))  # type: ignore[union-attr]
                    else:
                        any_success = True
                        observation = str(result)

                    self._total_obs_chars += len(observation)

                    messages.append(Msg(
                        role="tool",
                        content=observation,
                        tool_call_id=call_id,
                        name=tool_name,
                    ))

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
                        content=reason, steps=step + 1, terminated=True,
                        termination_reason="consecutive_errors",
                    )

                # Token burn guard
                if self._total_obs_chars > self._cfg.token_burn_hard_chars:
                    return ExecutorResult(
                        content=("[TERMINATED] Data limit (50k chars) reached. "
                                 "Summarizing now."),
                        steps=step + 1,
                        terminated=True,
                        termination_reason="token_burn",
                    )
                if self._total_obs_chars > self._cfg.token_burn_warn_chars:
                    messages.append(Msg(
                        role="user",
                        content="[SYSTEM: 30k+ chars gathered. Stop researching. Synthesize now.]",
                    ))

                continue

            # ── Final answer ──────────────────────────────────────────────────
            if content:
                total_ms = int((time.monotonic() - wall_start) * 1000)
                logger.info(
                    "executor done agent_id=%s steps=%d ms=%d",
                    agent_id, step + 1, total_ms,
                )
                return ExecutorResult(
                    content=content,
                    steps=step + 1,
                    total_ms=total_ms,
                )

        # Max steps reached
        return ExecutorResult(
            content="[Agent reached maximum reasoning steps]",
            steps=self._cfg.max_steps,
            terminated=True,
            termination_reason="max_steps",
        )

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
            result = await self._tools.call(tool_name, args)  # type: ignore[union-attr]
            logger.info("executor tool.result step=%d tool=%s len=%d", step, tool_name, len(result))
            return result

        except GeneratorExit:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("executor tool.error step=%d tool=%s: %s", step, tool_name, exc)
            return f"Error executing {tool_name}: {exc}"
