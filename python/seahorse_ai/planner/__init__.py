"""seahorse_ai.planner — ReAct (Reason + Act) agent planning pipeline.

Architecture (9-10/10 level)
-------------------------------
ReActPlanner.run(request)
  │
  ├── prompts.classify_intent()   — two-tier intent classifier
  │   (keyword fast-path + LLM fallback)
  │
  ├── StrategyPlanner.plan()      — cached master plan generation
  │   (TTL=5min, max_size=256)
  │
  ├── ReActExecutor.run()         — pure ReAct loop
  │   ├── LLM step (with tier escalation)
  │   ├── parallel tool execution (asyncio.gather)
  │   ├── CircuitBreaker tracking
  │   └── token burn guards
  │
  └── MemoryRecorder.record()     — rate-limited background summarization
      (min_interval=5s, min_messages=3)

Public API: ReActPlanner(llm, tools, ...) → .run(AgentRequest) → AgentResponse
The API is identical to the legacy planner.py for full backward compatibility.
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Protocol, runtime_checkable

import anyio

from seahorse_ai.core.observability import get_tracer, setup_telemetry
from seahorse_ai.core.schemas import AgentRequest, AgentResponse, Message
from seahorse_ai.planner.circuit_breaker import CircuitBreaker
from seahorse_ai.planner.executor import ExecutorConfig, ReActExecutor
from seahorse_ai.planner.fast_path import (
    FastPathRouter,
    classify_structured_intent,
)
from seahorse_ai.planner.memory_recorder import MemoryRecorder
from seahorse_ai.planner.strategy import StrategyPlanner
from seahorse_ai.prompts import (
    MEMORY_NUDGE,
    REALTIME_NUDGE,
    build_system_prompt,
)
from seahorse_ai.skills.base import SeahorseSkill

logger = logging.getLogger(__name__)


# ── Database Pooling (Finding #17) ───────────────────────────────────────────

_pool: Any | None = None


async def _get_pool() -> Any:
    global _pool
    import asyncpg

    if _pool is None:
        pg_uri = os.environ.get("SEAHORSE_PG_URI")
        if not pg_uri:
            return None
        _pool = await asyncpg.create_pool(pg_uri, min_size=2, max_size=10)
    return _pool


# ── Protocols (kept for type-safety and mocking in tests) ─────────────────────


class LLMBackend(Protocol):
    """Any object that can complete a list of messages with tier support."""

    async def complete(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        tier: str = "worker",
    ) -> str | dict[str, object]:
        """Complete a list of messages using the specified LLM tier.

        Args:
            messages: Conversation history.
            tools: Optional OpenAI-format tool definitions.
            tier: LLM tier to use (e.g., 'worker', 'strategist').

        """
        ...


@runtime_checkable
class ToolRegistry(Protocol):
    """Any object that can dispatch a named tool call."""

    async def call(self, name: str, args: dict[str, object]) -> str:
        """Call a tool by name with arguments.

        Args:
            name: Tool name.
            args: Map of argument names to values.

        """
        ...


# ── Main Planner ──────────────────────────────────────────────────────────────


class ReActPlanner:
    """High-performance ReAct agent orchestrator.

    Composes four specialized components:
    - StrategyPlanner  : generates + caches master plans
    - ReActExecutor    : runs the step loop, calls tools
    - CircuitBreaker   : tracks errors, triggers termination
    - MemoryRecorder   : rate-limited background memory
    """

    def __init__(
        self,
        llm: LLMBackend,
        tools: ToolRegistry | None = None,
        skills: list[SeahorseSkill] | None = None,
        max_steps: int = 8,
        default_tier: str = "worker",
        step_timeout_seconds: int = 120,
        global_timeout_seconds: int = 600,
        identity_prompt: str | None = None,
        enable_hybrid: bool = True,
        hybrid_complexity_threshold: int = 4,
    ) -> None:
        """Initialize the ReActPlanner with its sub-components.

        Args:
            llm: The LLM backend for planning and execution.
            tools: Optional tool registry. Defaults to a standard registry.
            skills: Optional list of SeahorseSkill objects to define capabilities.
            max_steps: Maximum ReAct loop iterations.
            default_tier: Default LLM tier ('worker').
            step_timeout_seconds: Timeout per iteration.
            global_timeout_seconds: Total execution timeout.
            identity_prompt: Optional extra system instruction for identity.
            enable_hybrid: Enable the hybrid orchestrator for complex tasks.
            hybrid_complexity_threshold: Minimum complexity to activate hybrid mode.

        """
        self._llm = llm
        self._tools = tools or self._default_tools()
        self._skills = skills or []
        self._default_tier = default_tier
        self._identity_prompt = identity_prompt
        self._enable_hybrid = enable_hybrid
        self._hybrid_complexity_threshold = hybrid_complexity_threshold

        # Build sub-components
        self._circuit_breaker = CircuitBreaker()
        self._strategy = StrategyPlanner(llm)
        self._memory = MemoryRecorder(llm, self._tools)
        self._fast_path = FastPathRouter(self._tools, llm_backend=self._llm)
        self._cfg = ExecutorConfig(
            max_steps=max_steps,
            step_timeout_seconds=step_timeout_seconds,
            global_timeout_seconds=global_timeout_seconds,
        )

        # Hybrid orchestrator (lazy — only used when complexity >= threshold)
        self._hybrid: Any | None = None

        setup_telemetry()  # idempotent

    # ── Public API ─────────────────────────────────────────────────────────────

    async def run(self, request: AgentRequest) -> AgentResponse:
        """Execute the ReAct planning loop and return the final response."""
        tracer = get_tracer("seahorse.planner")
        with tracer.start_as_current_span("agent.run") as span:
            # ── 0. Persist Execution State (Phase 2: Durable Execution) ────
            execution_id = uuid.uuid4()
            _set_span(
                span,
                {
                    "agent.id": request.agent_id,
                    "agent.execution_id": str(execution_id),
                    "agent.prompt_len": len(request.prompt),
                    "agent.max_steps": self._cfg.max_steps,
                },
            )

            # Initial state persistence
            await self._persist_execution(
                execution_id, request.agent_id, request.prompt, request.history
            )

            # Fresh circuit breaker per request
            self._circuit_breaker = CircuitBreaker()

            # ── 1. Structured Intent (1 LLM call → intent+action+entity) ──
            # OPTIMIZATION: Skip classification for sub-agents (crew_*, sub_*) or short queries
            is_subagent = request.agent_id.startswith(("crew_", "sub_"))
            is_simple_query = len(request.prompt.split()) <= 3
            if is_subagent or is_simple_query:
                from seahorse_ai.planner.fast_path import StructuredIntent

                si = StructuredIntent(intent="GENERAL", action="CHAT", complexity=3)
            else:
                try:
                    with anyio.fail_after(15.0):
                        si = await classify_structured_intent(
                            request.prompt,
                            self._llm,
                            request.history,
                        )
                except TimeoutError:
                    logger.warning(
                        "agent.run intent classification timed out — falling back to GENERAL"
                    )
                    from seahorse_ai.planner.fast_path import StructuredIntent

                    si = StructuredIntent(intent="GENERAL", action="CHAT")

            intent = si.raw_category or si.intent
            logger.info(
                "agent.run intent=%s action=%s entity=%r agent_id=%s (crew=%s)",
                si.intent,
                si.action,
                si.entity,
                request.agent_id,
                is_subagent,
            )

            # ── 2. Fast Path — bypass ReAct if action is simple ────────────
            fast = await self._fast_path.try_route(
                si, request.agent_id, request.prompt, request.history
            )
            if fast is not None:
                _set_span(
                    span,
                    {
                        "agent.fast_path": True,
                        "agent.action": si.action,
                        "agent.intent": intent,
                    },
                )
                logger.info(
                    "agent.run FAST_PATH action=%s agent_id=%s",
                    si.action,
                    request.agent_id,
                )
                return fast  # Done! 1 LLM call total ⚡

            # ── 2.5 Hybrid Orchestrator — iterative multi-agent for complex tasks ──
            # NEVER trigger for sub-agents (crew_*, sub_*) to avoid infinite recursion
            is_subagent = request.agent_id.startswith(("crew_", "sub_"))
            if (
                self._enable_hybrid
                and si.complexity >= self._hybrid_complexity_threshold
                and not is_subagent
            ):
                logger.info(
                    "agent.run HYBRID mode complexity=%d agent_id=%s",
                    si.complexity,
                    request.agent_id,
                )
                _set_span(span, {"agent.hybrid_mode": True, "agent.complexity": si.complexity})
                return await self._run_hybrid(request)

            # ── 3. Build system messages (full ReAct path) ─────────────────
            sys_prompt = build_system_prompt(skills=self._skills, tone=si.tone, intent=intent)
            if self._identity_prompt:
                sys_prompt += f"\n\n{self._identity_prompt}"

            messages: list[Message] = [
                Message(role="system", content=sys_prompt),
            ]
            if request.history:
                messages.extend(request.history)

            prompt_content = request.prompt
            if intent == "PUBLIC_REALTIME":
                prompt_content = f"{prompt_content}\n\n{REALTIME_NUDGE}"
            elif intent in ("PRIVATE_MEMORY", "DATABASE"):
                prompt_content = f"{prompt_content}\n\n{MEMORY_NUDGE}"
            messages.append(Message(role="user", content=prompt_content))

            # 4. Strategy plan (cached) — only for medium+ complexity
            # Complexity 1-2: skip (simple tasks don't need a plan)
            # Complexity 3:   thinker generates plan (good enough, cheap)
            # Complexity 4-5: strategist generates plan (expensive, best quality)
            if si.complexity >= 3 and intent not in ("GENERAL", "GREET"):
                plan = await self._strategy.plan(request.prompt, complexity=si.complexity)
                messages.insert(
                    1,
                    Message(
                        role="system",
                        content=f"{plan}\n\n[SYSTEM] Follow the plan above before answering.",
                    ),
                )

            # 5. Build OpenAI tool definitions — filtered by intent
            openai_tools = getattr(self._tools, "to_openai_tools_for_intent", None)
            if openai_tools is not None:
                openai_tools = openai_tools(intent)
            else:
                openai_tools = getattr(self._tools, "to_openai_tools", lambda: [])()

            # 6. Execute ReAct loop
            try:
                executor = ReActExecutor(
                    llm=self._llm,
                    tools=self._tools,
                    circuit_breaker=self._circuit_breaker,
                    config=self._cfg,
                    step_callback=lambda msgs: self._update_execution(execution_id, msgs),
                )
                result = await executor.run(
                    messages,
                    openai_tools,
                    agent_id=request.agent_id,
                )

                # Update final status
                await self._update_execution(
                    execution_id, messages, status="DONE" if not result.terminated else "TERMINATED"
                )

                # 7. Final synthesis
                content = result.content

                # OPTIMIZATION: Removed redundant _synthesize step to save token costs.
                # The worker model output should be presented directly.

                # 8. Background memory (rate-limited)
                await self._memory.record(messages, agent_id=request.agent_id)

                _set_span(
                    span,
                    {
                        "agent.steps_taken": result.steps,
                        "agent.total_ms": result.total_ms,
                        "agent.status": "terminated" if result.terminated else "done",
                    },
                )

                return AgentResponse(
                    content=content,
                    steps=result.steps,
                    agent_id=request.agent_id,
                    elapsed_ms=result.total_ms,
                    terminated=result.terminated,
                    termination_reason=result.termination_reason,
                    image_paths=result.image_paths,
                )

            except Exception as e:
                await self._update_execution(execution_id, messages, status="FAILED")
                raise e

    # ── Hybrid orchestrator ──────────────────────────────────────────────────

    async def _run_hybrid(self, request: AgentRequest) -> AgentResponse:
        """Delegate to the HybridOrchestrator for complex multi-step tasks."""
        if self._hybrid is None:
            from seahorse_ai.planner.hybrid_orchestrator import HybridOrchestrator
            from seahorse_ai.planner.hybrid_schemas import HybridConfig

            self._hybrid = HybridOrchestrator(
                llm=self._llm,
                tools=self._tools,
                config=HybridConfig(
                    max_steps_per_subtask=8,
                    step_timeout_seconds=self._cfg.step_timeout_seconds,
                    global_timeout_seconds=self._cfg.global_timeout_seconds,
                ),
                identity_prompt=self._identity_prompt,
            )

        return await self._hybrid.run(request)

    # ── Private helpers ────────────────────────────────────────────────────────

    async def _synthesize(self, messages: list[Message], content: str, original_prompt: str) -> str:
        """Run a final synthesis pass with the strategist model."""
        try:
            logger.info("agent.run synthesizing with strategist model")
            synth_msgs = messages + [
                Message(role="assistant", content=content),
                Message(
                    role="user",
                    content=(
                        "Provide a natural response to the user based on the tool results above.\n"
                        "RULES:\n"
                        "1. BE CONCISE. Just answer the user's latest question. DO NOT summarize past tasks you have already completed.\n"
                        "2. PRESERVE TECHNICAL TAGS: If you see `ECHART_JSON:/path/to/file.json` in the previous assistant message, you MUST include it at the end of your response so the system can render the chart.\n"
                        "3. ABSOLUTE ACCURACY: All numbers (Correlation, Mean, etc.) MUST match the tool results EXACTLY. Do not approximate or rewrite them.\n"
                        "4. REPLY in the same language the user used (Thai/English)."
                    ),
                ),
            ]
            result = await self._llm.complete(synth_msgs, tier="strategist")
            if isinstance(result, dict):
                return str(result.get("content", content))
            return str(result)
        except Exception as exc:  # noqa: BLE001
            logger.error("agent.run synthesis failed: %s", exc)
            return content

    async def _persist_execution(
        self, execution_id: uuid.UUID, agent_id: str, prompt: str, history: list[Message] | None
    ) -> None:
        """Create initial execution record in Postgres."""
        import json

        pool = await _get_pool()
        if not pool:
            return
        try:
            async with pool.acquire() as conn:
                import msgspec

                hist_json = (
                    json.dumps([msgspec.to_builtins(h) for h in history]) if history else None
                )
                await conn.execute(
                    """
                    INSERT INTO seahorse_executions (id, agent_id, prompt, history, status)
                    VALUES ($1, $2, $3, $4, 'RUNNING')
                """,
                    execution_id,
                    agent_id,
                    prompt,
                    hist_json,
                )
        except Exception as e:
            logger.error("planner._persist_execution failed: %s", e)

    async def _update_execution(
        self, execution_id: uuid.UUID, messages: list[Message], status: str = "RUNNING"
    ) -> None:
        """Update existing execution record with current conversation state."""
        import json

        pool = await _get_pool()
        if not pool:
            return
        try:
            async with pool.acquire() as conn:
                import msgspec

                msgs_json = json.dumps([msgspec.to_builtins(m) for m in messages])
                await conn.execute(
                    """
                    UPDATE seahorse_executions 
                    SET messages = $1, status = $2, updated_at = NOW()
                    WHERE id = $3
                """,
                    msgs_json,
                    status,
                    execution_id,
                )
                logger.info("planner._update_execution: updated id=%s", execution_id)
        except Exception as e:
            logger.error("planner._update_execution failed: %s", e)

    @staticmethod
    def _default_tools() -> ToolRegistry:
        from seahorse_ai.tools import make_default_registry

        return make_default_registry()


# ── Module-level helpers ───────────────────────────────────────────────────────


async def _classify_tier(llm: object, prompt: str, default: str) -> str:
    # Ensure we handle potential attribute errors or signature mismatches in mocks
    try:
        if hasattr(llm, "classify_intent"):
            import inspect

            if inspect.iscoroutinefunction(llm.classify_intent):
                tier = await llm.classify_intent(prompt)  # type: ignore
            else:
                tier = llm.classify_intent(prompt)  # type: ignore
        else:
            tier = default
    except Exception:
        tier = default
    return "thinker" if tier == "strategist" else tier


def _set_span(span: object, attrs: dict[str, object]) -> None:
    try:
        for k, v in attrs.items():
            span.set_attribute(k, v)  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        pass
