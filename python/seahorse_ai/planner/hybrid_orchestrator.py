"""seahorse_ai.planner.hybrid_orchestrator — Hybrid Agent Pattern.

Orchestrator → parallel Subagents → Critic → 3-tier Memory → Targeted Replan.

This is the top-level entry point for the "Plan–Execute–Persist–Evaluate"
loop described in the design doc.  It replaces the single-shot ReAct flow
with an iterative multi-agent architecture while staying fully backward-
compatible with the existing ``AgentRequest``/``AgentResponse`` contract.

Key properties:
- Lightweight intent classification via FastPath (< 50ms), LLM only as fallback.
- Dependency graph decomposition → true parallelism via ``anyio.create_task_group``.
- Each subagent has its own context window (isolation).
- Critic never sees chain-of-thought — only output, goal, criteria.
- 3-tier memory with ≤20% injection cap and delta-only updates.
- Targeted replan: ``partial`` verdict reruns only failed subtasks.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

import anyio

from seahorse_ai.core.schemas import AgentRequest, AgentResponse, Message
from seahorse_ai.planner.circuit_breaker import CircuitBreaker
from seahorse_ai.planner.critic import CriticAgent
from seahorse_ai.planner.decomposer import TaskDecomposer
from seahorse_ai.planner.executor import ExecutorConfig, ReActExecutor
from seahorse_ai.planner.hybrid_schemas import (
    CriticVerdict,
    DecompositionGraph,
    HybridConfig,
    SubtaskNode,
    SubtaskResult,
    TrialArtifact,
)
from seahorse_ai.planner.session_memory import SessionMemory
from seahorse_ai.prompts import build_system_prompt

logger = logging.getLogger(__name__)


class HybridOrchestrator:
    """Iterative multi-agent orchestrator with critic-gated output.

    Lifecycle per request:
    1. Classify intent (lightweight).
    2. Decompose into dependency graph.
    3. Execute ready subtasks in parallel (each with isolated context).
    4. Collect results → persist to Tier 2 memory.
    5. Critic evaluates (output only, no chain-of-thought).
    6. pass → return.  partial → targeted replan.  reject → full replan.
    7. Loop back to step 3 (or 2 on reject) until pass or budget exhausted.
    """

    def __init__(
        self,
        llm: Any,
        tools: Any | None = None,
        config: HybridConfig | None = None,
        identity_prompt: str | None = None,
    ) -> None:
        from seahorse_ai.core.llm import get_llm
        self._llm = llm # worker
        self._thinker_llm = get_llm(tier="thinker")
        self._strategist_llm = get_llm(tier="strategist")
        
        self._tools = tools
        self._cfg = config or HybridConfig()
        self._identity_prompt = identity_prompt

        self._decomposer = TaskDecomposer(self._thinker_llm)
        self._critic = CriticAgent(self._thinker_llm, use_llm=self._cfg.use_llm_critic)
        self._complexity_cache: dict[str, int] = {}

        # ── Load Dynamic Skills ───────────────────────────────────────────────
        from seahorse_ai.skills.base import registry as skill_registry
        from seahorse_ai.tools import make_default_registry

        skill_registry.load_plugins("python/seahorse_ai/skills/manifests")
        # Resolve against the provided tools registry, falling back to default
        target_registry = self._tools or make_default_registry()
        skill_registry.resolve_tools(target_registry)

    async def run(self, request: AgentRequest) -> AgentResponse:
        """Execute the full hybrid loop and return a single AgentResponse."""
        wall_start = time.monotonic()
        session_id = f"hybrid_{request.agent_id}_{uuid.uuid4().hex[:8]}"

        memory = SessionMemory(
            session_id=session_id,
            tools=self._tools,
        )

        # ── 1. Classify intent (reuse existing fast_path for complexity) ─────
        si = await self._classify_intent(request)
        complexity = si.complexity
        intent = si.intent
        logger.info(
            "hybrid.run agent_id=%s complexity=%d intent=%s session=%s",
            request.agent_id,
            complexity,
            intent,
            session_id,
        )

        # ── 1b. Auto Skill Selection ─────────────────────────────────────────
        matched_skill = await self._match_skill(request.prompt)
        skill_snippet = ""
        if matched_skill:
            skill_snippet = matched_skill.get_prompt_snippet()
            logger.info("hybrid.run auto-selected skill: %s", matched_skill.name)

        # ── 2. Decompose ─────────────────────────────────────────────────────
        graph = await self._decomposer.decompose(
            goal=request.prompt,
            history=request.history or None,
            complexity=complexity,
            skill_context=skill_snippet,  # Pass the skill's specific rules
        )
        memory.put("plan_summary", graph.goal)
        logger.info(
            "hybrid.run decomposed into %d subtasks (graph=%s)",
            len(graph.nodes),
            [n.id for n in graph.nodes],
        )

        # ── 3-7. Outer loop ──────────────────────────────────────────────────
        best_content = ""
        total_steps = 0

        for trial in range(self._cfg.max_trials):
            elapsed = time.monotonic() - wall_start
            if elapsed > self._cfg.global_timeout_seconds:
                logger.warning("hybrid.run global timeout at trial %d", trial)
                break

            # ── 3. Execute ready subtasks in parallel ─────────────────────
            ready = graph.ready_nodes()
            if not ready and not graph.all_done():
                logger.error("hybrid.run deadlock: no ready nodes but graph not done")
                break

            subtask_results: list[SubtaskResult] = []

            while ready:
                batch_results: list[SubtaskResult] = [
                    SubtaskResult(subtask_id="", content="")
                ] * len(ready)

                async def _run_subtask(
                    idx: int,
                    node: SubtaskNode,
                    results: list[SubtaskResult] = batch_results,
                ) -> None:
                    results[idx] = await self._execute_subtask(
                        node, graph, memory, request, intent, skill_snippet
                    )

                async with anyio.create_task_group() as tg:
                    for i, node in enumerate(ready):
                        node.status = "running"
                        tg.start_soon(_run_subtask, i, node)

                for sr, node in zip(batch_results, ready, strict=False):
                    node.status = "done" if not sr.terminated else "failed"
                    node.result_summary = sr.content[:300] if sr.content else ""
                    subtask_results.append(sr)
                    total_steps += sr.steps

                ready = graph.ready_nodes()

            # ── 4. Persist trial ──────────────────────────────────────────
            trial_artifact = TrialArtifact(
                trial_id=trial,
                plan_summary=graph.goal,
                subtask_results=subtask_results,
                total_steps=total_steps,
                total_ms=int((time.monotonic() - wall_start) * 1000),
            )
            memory.record_trial(trial_artifact)

            best_content = self._merge_results(subtask_results)

            # ── 5. Critic evaluation ──────────────────────────────────────
            verdict = await self._critic.evaluate(
                goal=graph.goal,
                success_criteria=graph.success_criteria,
                subtask_results=subtask_results,
            )
            logger.info(
                "hybrid.run trial=%d verdict=%s reason=%s",
                trial,
                verdict.verdict,
                verdict.reason,
            )

            # ── 6. Decide ────────────────────────────────────────────────
            if verdict.verdict == "pass":
                await memory.persist_lesson(
                    f"Goal '{graph.goal[:100]}' succeeded on trial {trial}."
                )
                break

            if verdict.verdict == "partial":
                self._targeted_replan(graph, verdict)
            else:
                for n in graph.nodes:
                    if n.status != "done":
                        n.status = "pending"

        total_ms = int((time.monotonic() - wall_start) * 1000)
        logger.info(
            "hybrid.run done session=%s steps=%d ms=%d trials=%d",
            session_id,
            total_steps,
            total_ms,
            len(memory.trials),
        )

        # ── 7. Final Strategist Synthesis ─────────────────────────────
        # If we reached here without a 'pass' and have some content,
        # OR if content is empty (budget exhausted), synthesize final reason.
        if not best_content or (len(memory.trials) >= self._cfg.max_trials):
            logger.info("hybrid.run: synthesizing final failure/budget response")
            # Pull the late verdict and artifacts to explain 'why'
            last_verdict = verdict.reason if "verdict" in locals() else "Budget exhausted"

            # Use Strategist tier for final synthesis
            final_prompt = [
                Message(
                    role="system",
                    content=(
                        "You are Seahorse Strategic Analyst. "
                        "The agent failed to fully complete the goal. "
                        f"Goal: {request.prompt}\n"
                        f"Reason: {last_verdict}\n"
                        "Provide a polite, professional explanation in the user's language."
                    ),
                ),
                Message(role="user", content="Explain why the task could not be completed."),
            ]
            try:
                final_res = await self._strategist_llm.complete(final_prompt, tier="strategist")
                best_content = str(
                    final_res.get("content", final_res)
                    if isinstance(final_res, dict)
                    else final_res
                )
            except Exception as e:
                logger.error("hybrid final synthesis failed: %s", e)
                best_content = best_content or "ขออภัยครับ ระบบไม่สามารถดำเนินการตามคำขอได้สำเร็จในขณะนี้"

        return AgentResponse(
            content=best_content,
            steps=total_steps,
            agent_id=request.agent_id,
            elapsed_ms=total_ms,
            terminated=not best_content,
            termination_reason="budget_exhausted" if not best_content else None,
        )

    # ── Subagent execution (isolated context) ─────────────────────────────────

    async def _execute_subtask(
        self,
        node: SubtaskNode,
        graph: DecompositionGraph,
        memory: SessionMemory,
        request: AgentRequest,
        intent: str = "GENERAL",
        skill_context: str = "",
    ) -> SubtaskResult:
        """Run a single subtask in an isolated context window."""
        tier3 = await memory.search_relevant(node.description, top_k=3)

        context_block = memory.build_context_block(
            subtask_description=node.description,
            goal=graph.goal,
            success_criteria=graph.success_criteria,
            tier3_results=tier3 if tier3 else None,
        )

        sys_prompt = build_system_prompt(intent=intent)
        if self._identity_prompt:
            sys_prompt += f"\n\n{self._identity_prompt}"

        messages: list[Message] = [
            Message(role="system", content=sys_prompt),
            Message(
                role="system",
                content=f"{skill_context}\n\n{context_block}" if skill_context else context_block,
            ),
            Message(role="user", content=node.description),
        ]

        cb = CircuitBreaker()
        cfg = ExecutorConfig(
            max_steps=5,
            step_timeout_seconds=self._cfg.step_timeout_seconds,
            token_burn_warn_chars=10_000,
            token_burn_hard_chars=20_000,
        )

        # Use intent-specific tool filtering to save tokens
        if hasattr(self._tools, "to_openai_tools_for_intent"):
            openai_tools = self._tools.to_openai_tools_for_intent(intent)
        else:
            openai_tools = getattr(self._tools, "to_openai_tools", lambda: [])()

        # AUTO-SEARCH: For PUBLIC_REALTIME, pre-fetch web data so the AI has
        # current facts. This bypasses the worker model's tendency to answer
        # from stale training data without calling tools.
        if intent == "PUBLIC_REALTIME":
            try:
                search_fn = self._tools.get("web_search")
                if search_fn:
                    logger.info("hybrid: auto-search for PUBLIC_REALTIME: %s", node.description)
                    search_result = await search_fn(query=node.description)
                    messages.append(Message(
                        role="system",
                        content=f"## Live Search Results (use this data to answer)\n{search_result}",
                    ))
                    # Prevent LLM from searching again to save time and tokens
                    openai_tools = [t for t in openai_tools if t["function"]["name"] != "web_search"]
            except Exception as exc:
                logger.warning("hybrid: auto-search failed: %s", exc)

        executor = ReActExecutor(
            llm=self._llm,
            tools=self._tools,
            circuit_breaker=cb,
            config=cfg,
        )
        
        res = await executor.run(messages, openai_tools, agent_id=node.assigned_agent)
        
        # 3. Save to Tier 2 memory
        return SubtaskResult(
            subtask_id=node.id,
            content=res.content,
            evidence=res.evidence,  # Pass evidence from ReActExecutor
            steps=res.steps,
            terminated=res.terminated,
            termination_reason=res.termination_reason,
            tool_names_used=[t.name for t in messages if t.role == "tool" and t.name],
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _match_skill(self, prompt: str) -> Any:
        """Match the user prompt to the best skill using semantic discovery (LLM)."""
        from seahorse_ai.skills.base import registry as skill_registry

        return await skill_registry.find_best_match(prompt, self._llm)

    async def _classify_intent(self, request: AgentRequest) -> Any:
        """Quick complexity/intent classification — reuse FastPath if available. Caches results."""
        if request.prompt in self._complexity_cache:
            return self._complexity_cache[request.prompt]

        try:
            from seahorse_ai.planner.fast_path import classify_structured_intent

            si = await classify_structured_intent(
                request.prompt, self._llm, request.history or []
            )
            self._complexity_cache[request.prompt] = si
            return si
        except Exception:
            # Fallback
            from seahorse_ai.planner.fast_path import StructuredIntent

            return StructuredIntent(intent="GENERAL", complexity=3)

    def _merge_results(self, results: list[SubtaskResult]) -> str:
        """Merge non-terminated subtask results into a single response."""
        parts = [r.content for r in results if r.content and not r.terminated]
        if not parts:
            terminated = [r for r in results if r.terminated]
            if terminated:
                return terminated[0].content
            return ""
        if len(parts) == 1:
            return parts[0]
        return "\n\n---\n\n".join(parts)

    def _targeted_replan(self, graph: DecompositionGraph, verdict: CriticVerdict) -> None:
        """Reset only the failed subtasks for re-execution."""
        failed_ids = set(verdict.failed_subtasks)
        for node in graph.nodes:
            if node.id in failed_ids:
                node.status = "pending"
                node.result_summary = None
                logger.info("hybrid targeted_replan: resetting subtask %s", node.id)

    @staticmethod
    def _extract_tool_names(messages: list[Message]) -> list[str]:
        names: list[str] = []
        for m in messages:
            if m.tool_calls:
                for tc in m.tool_calls:
                    name = tc.get("function", {}).get("name")
                    if name and name not in names:
                        names.append(name)
        return names
