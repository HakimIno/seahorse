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
from typing import Protocol, runtime_checkable

from seahorse_ai.observability import get_tracer, setup_telemetry
from seahorse_ai.planner.circuit_breaker import CircuitBreaker
from seahorse_ai.planner.executor import ExecutorConfig, ReActExecutor
from seahorse_ai.planner.memory_recorder import MemoryRecorder
from seahorse_ai.planner.strategy import StrategyPlanner
from seahorse_ai.prompts import (
    MEMORY_NUDGE,
    REALTIME_NUDGE,
    build_system_prompt,
    classify_intent,
)
from seahorse_ai.schemas import AgentRequest, AgentResponse, Message

logger = logging.getLogger(__name__)


# ── Protocols (kept for type-safety and mocking in tests) ─────────────────────

class LLMBackend(Protocol):
    """Any object that can complete a list of messages with tier support."""
    async def complete(
        self, messages: list[Message], tools: list[dict] | None = None, tier: str = "worker"
    ) -> str | dict[str, object]: ...


@runtime_checkable
class ToolRegistry(Protocol):
    """Any object that can dispatch a named tool call."""
    async def call(self, name: str, args: dict[str, object]) -> str: ...


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
        max_steps: int = 15,
        default_tier: str = "worker",
        step_timeout_seconds: int = 30,
        global_timeout_seconds: int = 120,
    ) -> None:
        self._llm = llm
        self._tools = tools or self._default_tools()
        self._default_tier = default_tier

        # Build sub-components
        self._circuit_breaker = CircuitBreaker()
        self._strategy = StrategyPlanner(llm)
        self._memory = MemoryRecorder(llm, self._tools)
        self._cfg = ExecutorConfig(
            max_steps=max_steps,
            step_timeout_seconds=step_timeout_seconds,
            global_timeout_seconds=global_timeout_seconds,
        )
        setup_telemetry()  # idempotent

    # ── Public API ─────────────────────────────────────────────────────────────

    async def run(self, request: AgentRequest) -> AgentResponse:
        """Execute the agent pipeline and return the final response."""
        tracer = get_tracer("seahorse.planner")

        with tracer.start_as_current_span("agent.run") as span:
            _set_span(span, {
                "agent.id": request.agent_id,
                "agent.prompt_len": len(request.prompt),
                "agent.max_steps": self._cfg.max_steps,
            })

            # Fresh circuit breaker per request
            self._circuit_breaker = CircuitBreaker()

            # 1. Build system messages
            messages: list[Message] = [Message(role="system", content=build_system_prompt())]
            if request.history:
                messages.extend(request.history)

            # 2. Classify intent (two-tier: keyword → LLM fallback)
            intent = await classify_intent(request.prompt, self._llm)
            logger.info("agent.run intent=%s agent_id=%s", intent, request.agent_id)

            prompt_content = request.prompt
            if intent == "PUBLIC_REALTIME":
                prompt_content = f"{prompt_content}\n\n{REALTIME_NUDGE}"
            elif intent in ("PRIVATE_MEMORY", "DATABASE"):
                prompt_content = f"{prompt_content}\n\n{MEMORY_NUDGE}"
            messages.append(Message(role="user", content=prompt_content))

            # 3. Strategy plan (cached) for complex intents
            current_tier = _classify_tier(self._llm, request.prompt, self._default_tier)
            if current_tier in ("thinker", "strategist"):
                plan = await self._strategy.plan(request.prompt)
                messages.insert(1, Message(
                    role="system",
                    content=f"{plan}\n\n[SYSTEM] Follow the plan above before answering.",
                ))
                logger.info("agent.run strategy_cache_size=%d", self._strategy.cache_size)

            # 4. Build OpenAI tool definitions
            openai_tools = getattr(self._tools, "to_openai_tools", lambda: [])()

            # 5. Execute ReAct loop
            executor = ReActExecutor(
                llm=self._llm,
                tools=self._tools,
                circuit_breaker=self._circuit_breaker,
                config=self._cfg,
            )
            result = await executor.run(messages, openai_tools, agent_id=request.agent_id)

            # 6. Optional: final synthesis with strategist tier
            content = result.content
            if not result.terminated and current_tier == "strategist":
                content = await self._synthesize(messages, content, request.prompt)

            # 7. Background memory (rate-limited, non-blocking)
            asyncio.create_task(
                self._memory.record(messages, agent_id=request.agent_id)
            )

            _set_span(span, {
                "agent.steps_taken": result.steps,
                "agent.total_ms": result.total_ms,
                "agent.status": "terminated" if result.terminated else "done",
                "agent.intent": intent,
                "strategy.cache_size": self._strategy.cache_size,
            })

            return AgentResponse(
                content=content,
                steps=result.steps,
                agent_id=request.agent_id,
                elapsed_ms=result.total_ms,
                terminated=result.terminated,
                termination_reason=result.termination_reason,
            )

    # ── Private helpers ────────────────────────────────────────────────────────

    async def _synthesize(
        self, messages: list[Message], content: str, original_prompt: str
    ) -> str:
        """Run a final synthesis pass with the strategist model."""
        try:
            logger.info("agent.run synthesizing with strategist model")
            synth_msgs = messages + [
                Message(role="assistant", content=content),
                Message(role="user", content="สรุปคำตอบให้เป็นภาษากลยุทธ์ทางธุรกิจที่น่าสนใจ"),
            ]
            result = await self._llm.complete(synth_msgs, tier="strategist")
            return str(result.get("content", content) if isinstance(result, dict) else result)
        except Exception as exc:  # noqa: BLE001
            logger.error("agent.run synthesis failed: %s", exc)
            return content

    @staticmethod
    def _default_tools() -> ToolRegistry:
        from seahorse_ai.tools import make_default_registry
        return make_default_registry()


# ── Module-level helpers ───────────────────────────────────────────────────────

def _classify_tier(llm: object, prompt: str, default: str) -> str:
    tier = getattr(llm, "classify_intent", lambda p: default)(prompt)
    return "thinker" if tier == "strategist" else tier


def _set_span(span: object, attrs: dict[str, object]) -> None:
    try:
        for k, v in attrs.items():
            span.set_attribute(k, v)  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        pass
