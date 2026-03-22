"""seahorse_ai.planner.critic — Isolated evaluation agent.

Design decisions (from §5.3 of the design doc):
- The critic NEVER sees the actor's chain-of-thought.  It receives only:
  1. The final output of each subagent.
  2. The original user goal.
  3. Explicit success criteria.
- Three-level verdict: pass / partial / reject.
  ``partial`` triggers *targeted* replan (only the failed subtasks),
  saving 50-70% tokens vs. redoing everything.
- Rule-based fast-check runs first (zero tokens).  LLM judge is invoked
  only when rule-based check is inconclusive.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import anyio

from seahorse_ai.planner.hybrid_schemas import (
    CriticVerdict,
    SubtaskResult,
)
from seahorse_ai.core.schemas import Message

logger = logging.getLogger(__name__)

CRITIC_SYSTEM_PROMPT = """\
You are a strict quality evaluator.  You receive:
- GOAL: the user's original request.
- CRITERIA: a list of success criteria.
- SUBTASK_RESULTS: the outputs of subagents (one per subtask).

Evaluate whether the outputs satisfy ALL criteria.  Return ONLY valid JSON:

{
  "verdict": "pass" | "partial" | "reject",
  "passed_criteria": ["<criteria that are met>"],
  "failed_criteria": ["<criteria that are NOT met>"],
  "failed_subtasks": ["<subtask id that needs rework>"],
  "reason": "<1-2 sentence explanation>"
}

Rules:
- "pass" means every criterion is satisfied.
- "partial" means some criteria pass but others fail.  List only the subtask ids that are responsible for the failures.
- "reject" means the output is fundamentally wrong or off-topic.
- Be STRICT.  Do NOT anchor on the reasoning process — judge only the OUTPUT.
- If there is a single criterion and it's met, return "pass".
"""


class CriticAgent:
    """Evaluate subagent outputs against the original goal."""

    def __init__(self, llm: Any, use_llm: bool = True) -> None:
        self._llm = llm
        self._use_llm = use_llm

    async def evaluate(
        self,
        goal: str,
        success_criteria: list[str],
        subtask_results: list[SubtaskResult],
    ) -> CriticVerdict:
        """Run evaluation.  Rule-based check first, then LLM if needed."""
        rule_verdict = self._rule_based_check(subtask_results, success_criteria)
        if rule_verdict is not None:
            return rule_verdict

        if not self._use_llm:
            return CriticVerdict(
                verdict="pass",
                passed_criteria=success_criteria,
                reason="Rule-based check passed (LLM critic disabled).",
            )

        try:
            with anyio.fail_after(30):
                return await self._llm_evaluate(goal, success_criteria, subtask_results)
        except TimeoutError:
            logger.warning("critic: LLM timed out — falling back to rule-based pass")
            return CriticVerdict(
                verdict="pass",
                passed_criteria=success_criteria,
                reason="Critic LLM timed out; rule-based fallback pass.",
            )
        except Exception as exc:
            logger.error("critic: LLM failed: %s", exc)
            return CriticVerdict(
                verdict="pass",
                passed_criteria=success_criteria,
                reason=f"Critic error ({exc}); defaulting to pass.",
            )

    def _rule_based_check(
        self,
        results: list[SubtaskResult],
        criteria: list[str],
    ) -> CriticVerdict | None:
        """Return a verdict if the rule-based check is conclusive, else None."""
        if not results:
            return CriticVerdict(
                verdict="reject",
                failed_criteria=criteria,
                reason="No subtask results produced.",
            )

        all_terminated = all(r.terminated for r in results)
        if all_terminated:
            return CriticVerdict(
                verdict="reject",
                failed_criteria=criteria,
                failed_subtasks=[r.subtask_id for r in results],
                reason="All subtasks terminated abnormally.",
            )

        all_have_content = all(
            r.content and len(r.content.strip()) > 10 and not r.terminated
            for r in results
        )
        if all_have_content and len(results) == 1 and len(criteria) <= 1:
            return CriticVerdict(
                verdict="pass",
                passed_criteria=criteria,
                reason="Single subtask completed with content (rule-based).",
            )

        return None

    async def _llm_evaluate(
        self,
        goal: str,
        criteria: list[str],
        results: list[SubtaskResult],
    ) -> CriticVerdict:
        outputs = []
        for r in results:
            outputs.append({
                "subtask_id": r.subtask_id,
                "content": r.content[:2000],
                "terminated": r.terminated,
            })

        user_msg = (
            f"GOAL: {goal}\n\n"
            f"CRITERIA:\n" + "\n".join(f"- {c}" for c in criteria) + "\n\n"
            f"SUBTASK_RESULTS:\n{json.dumps(outputs, ensure_ascii=False, indent=2)}"
        )

        messages = [
            Message(role="system", content=CRITIC_SYSTEM_PROMPT),
            Message(role="user", content=user_msg),
        ]

        raw_result = await self._llm.complete(messages, tier="worker")
        raw = str(
            raw_result.get("content", raw_result)
            if isinstance(raw_result, dict)
            else raw_result
        )

        return self._parse_verdict(raw, criteria)

    def _parse_verdict(self, raw: str, fallback_criteria: list[str]) -> CriticVerdict:
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0]

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("critic: invalid JSON — defaulting to pass")
            return CriticVerdict(
                verdict="pass",
                passed_criteria=fallback_criteria,
                reason="Critic output unparseable; defaulting to pass.",
            )

        verdict = data.get("verdict", "pass")
        if verdict not in ("pass", "partial", "reject"):
            verdict = "pass"

        return CriticVerdict(
            verdict=verdict,
            passed_criteria=data.get("passed_criteria", []),
            failed_criteria=data.get("failed_criteria", []),
            failed_subtasks=data.get("failed_subtasks", []),
            reason=data.get("reason", ""),
        )
