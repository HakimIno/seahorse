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
        self._fast_path = FastPathRouter(self._tools, llm_backend=self._llm)
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

            # ── 1. Structured Intent (1 LLM call → intent+action+entity) ──
            try:
                si = await asyncio.wait_for(
                    classify_structured_intent(
                        request.prompt, self._llm, request.history,
                    ),
                    timeout=15.0  # Reduced timeout for fast worker
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "agent.run intent classification timed out — falling back to GENERAL"
                )
                from seahorse_ai.planner.fast_path import StructuredIntent
                si = StructuredIntent(intent="GENERAL", action="CHAT")
            intent = si.raw_category or si.intent
            logger.info(
                "agent.run intent=%s action=%s entity=%r agent_id=%s",
                si.intent,
                si.action,
                si.entity,
                request.agent_id,
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

            # ── 3. Build system messages (full ReAct path) ─────────────────
            messages: list[Message] = [
                Message(role="system", content=build_system_prompt()),
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
                self._llm, request.prompt, self._default_tier,
            )
            if current_tier == "strategist" and intent not in ("GENERAL", "GREET"):
                plan = await self._strategy.plan(request.prompt)
                messages.insert(1, Message(
                    role="system",
                    content=f"{plan}\n\n[SYSTEM] Follow the plan above before answering.",
                ))

            # 5. Build OpenAI tool definitions
            openai_tools = getattr(self._tools, "to_openai_tools", lambda: [])()

            # 6. Execute ReAct loop
            executor = ReActExecutor(
                llm=self._llm,
                tools=self._tools,
                circuit_breaker=self._circuit_breaker,
                config=self._cfg,
            )
            result = await executor.run(
                messages, openai_tools, agent_id=request.agent_id,
            )

            # 7. Final synthesis with strategist tier for complex or data-heavy results
            content = result.content
            is_data_intent = intent in ("DATABASE", "PRIVATE_MEMORY", "PUBLIC_REALTIME")
            if not result.terminated and (current_tier == "strategist" or is_data_intent):
                content = await self._synthesize(
                    messages, content, request.prompt,
                )

            # 8. Background memory (rate-limited, non-blocking)
            asyncio.create_task(
                self._memory.record(messages, agent_id=request.agent_id)
            )

            _set_span(span, {
                "agent.steps_taken": result.steps,
                "agent.total_ms": result.total_ms,
                "agent.status": "terminated" if result.terminated else "done",
                "agent.intent": intent,
                "agent.action": si.action,
                "strategy.cache_size": self._strategy.cache_size,
            })

            return AgentResponse(
                content=content,
                steps=result.steps,
                agent_id=request.agent_id,
                elapsed_ms=result.total_ms,
                terminated=result.terminated,
                termination_reason=result.termination_reason,
                image_paths=result.image_paths,
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
                Message(role="user", content=(
                    "You are an elite business strategy consultant. Summarize the raw data above for the user.\n"
                    "CRITICAL INSTRUCTIONS:\n"
                    "1. Respond in a natural, conversational executive tone (Natural Flow).\n"
                    "2. Avoid rigid or highly structured formats (Do NOT use mandatory headers like '# Summary' or force artificial sections).\n"
                    "3. Weave high-level analytical logic seamlessly into the narrative:\n"
                    "   - Identify non-obvious correlations or trends in the data.\n"
                    "   - If you spot risks or golden opportunities, integrate proactive recommendations naturally into the conversation.\n"
                    "4. Be concise and logically structured. Use bullet points ONLY when absolutely necessary. Minimize emojis (max 2 per response).\n"
                    "5. IMPORTANT: You MUST reply in the same language the user used to ask the question (e.g., if the user asked in Thai, reply entirely in Thai)."
                )),
            ]
            result = await self._llm.complete(synth_msgs, tier="strategist")
            if isinstance(result, dict):
                return str(result.get("content", content))
            return str(result)
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
