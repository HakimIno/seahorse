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

import asyncio
import logging
import os
import uuid
from typing import Any, Protocol, runtime_checkable

from seahorse_ai.observability import get_tracer, setup_telemetry
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
from seahorse_ai.schemas import AgentRequest, AgentResponse, Message
from seahorse_ai.skills.base import SeahorseSkill

logger = logging.getLogger(__name__)


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
        max_steps: int = 15,
        default_tier: str = "worker",
        step_timeout_seconds: int = 120,
        global_timeout_seconds: int = 600,
        identity_prompt: str | None = None,
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

        """
        self._llm = llm
        self._tools = tools or self._default_tools()
        self._skills = skills or []
        self._default_tier = default_tier
        self._identity_prompt = identity_prompt

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
            # OPTIMIZATION: Skip classification for sub-agents (crew_*)
            is_crew = request.agent_id.startswith("crew_")
            if is_crew:
                from seahorse_ai.planner.fast_path import StructuredIntent
                si = StructuredIntent(intent="GENERAL", action="CHAT", complexity=3)
            else:
                try:
                    si = await asyncio.wait_for(
                        classify_structured_intent(
                            request.prompt,
                            self._llm,
                            request.history,
                        ),
                        timeout=15.0,  # Reduced timeout for fast worker
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
                is_crew,
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

            # ── 2.5 Auto-Seahorse Mode - trigger multi-agent for complex tasks ──
            # NEVER trigger Auto-Seahorse Mode for sub-agents (crew_*) to avoid infinite recursion
            if si.complexity >= 4 and not request.agent_id.startswith("crew_"):
                logger.info(
                    "agent.run CROSS-OVER to Auto-Seahorse complexity=%d agent_id=%s",
                    si.complexity,
                    request.agent_id,
                )
                from seahorse_ai.tools.auto_seahorse import execute_auto_seahorse

                crew_result = await execute_auto_seahorse(request.prompt, team_hint=si.intent)
                
                # Unpack if execute_auto_seahorse returns a dict (content, image_paths)
                is_str = isinstance(crew_result, str)
                content = crew_result if is_str else crew_result.get("content", "")
                images = [] if is_str else crew_result.get("image_paths") or []

                _set_span(
                    span, {"agent.auto_seahorse_mode": True, "agent.complexity": si.complexity}
                )
                return AgentResponse(
                    content=content,
                    steps=1,  # Abstraction level
                    agent_id=request.agent_id,
                    elapsed_ms=0,  # Calculation delegated
                    image_paths=images if images else None,
                )

            # ── 3. Build system messages (full ReAct path) ─────────────────
            sys_prompt = build_system_prompt(skills=self._skills, tone=si.tone)
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

            # 4. Strategy plan (cached) for complex intents
            # Only use strategy for complex reasoning tasks to save latency
            current_tier = _classify_tier(
                self._llm,
                request.prompt,
                self._default_tier,
            )
            if current_tier == "strategist" and intent not in ("GENERAL", "GREET"):
                plan = await self._strategy.plan(request.prompt)
                messages.insert(
                    1,
                    Message(
                        role="system",
                        content=f"{plan}\n\n[SYSTEM] Follow the plan above before answering.",
                    ),
                )

            # 5. Build OpenAI tool definitions
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
                is_data_intent = intent in ("DATABASE", "PRIVATE_MEMORY", "PUBLIC_REALTIME")

                # OPTIMIZATION: Skip synthesis if is_direct OR if current agent is already a thinker/strategist
                skip_synthesis = getattr(result, "is_direct", False)
                is_elite_already = current_tier in ("thinker", "strategist")
                
                if (
                    not result.terminated
                    and not skip_synthesis
                    and not is_crew
                    and not is_elite_already
                    and is_data_intent
                ):
                    content = await self._synthesize(
                        messages,
                        content,
                        request.prompt,
                    )

                # 8. Background memory (rate-limited, non-blocking)
                asyncio.create_task(self._memory.record(messages, agent_id=request.agent_id))

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
                        "2. Avoid rigid business jargon unless specifically asked.\n"
                        "3. If you see patterns or risks related to the IMMEDIATE question, mention them briefly.\n"
                        "4. DISTINGUISH between 'Technical Timeouts' (system taking too long) and 'Service Failures' (DB offline). Do not hallucinate connection issues if it was just a timeout.\n"
                        "5. REPLY in the same language the user used (Thai/English)."
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

        import asyncpg

        pg_uri = os.environ.get("SEAHORSE_PG_URI")
        if not pg_uri:
            return
        try:
            conn = await asyncpg.connect(pg_uri)
            try:
                hist_json = json.dumps([h.model_dump() for h in history]) if history else None
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
            finally:
                await conn.close()
        except Exception as e:
            logger.error("planner._persist_execution failed: %s", e)

    async def _update_execution(
        self, execution_id: uuid.UUID, messages: list[Message], status: str = "RUNNING"
    ) -> None:
        """Update existing execution record with current conversation state."""
        import json

        import asyncpg

        pg_uri = os.environ.get("SEAHORSE_PG_URI")
        if not pg_uri:
            return
        try:
            conn = await asyncpg.connect(pg_uri)
            try:
                msgs_json = json.dumps([m.model_dump() for m in messages])
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
            finally:
                await conn.close()
        except Exception as e:
            logger.error("planner._update_execution failed: %s", e)

    @staticmethod
    def _default_tools() -> ToolRegistry:
        from seahorse_ai.tools import make_default_registry

        return make_default_registry()


# ── Module-level helpers ───────────────────────────────────────────────────────


def _classify_tier(llm: object, prompt: str, default: str) -> str:
    # Ensure we handle potential attribute errors or signature mismatches in mocks
    try:
        if hasattr(llm, "classify_intent"):
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
