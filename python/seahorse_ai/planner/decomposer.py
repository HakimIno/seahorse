"""seahorse_ai.planner.decomposer — Lightweight intent + dependency graph decomposition.

Design decisions (from §5.1 of the design doc):
- Intent classification uses the existing FastPath keyword router first (< 50ms).
  LLM-based classification is only invoked if the keyword router is inconclusive.
- Task decomposition outputs a **dependency graph**, not an ordered list, so the
  orchestrator can immediately identify independent subtasks and run them in parallel.
- Simple prompts (greet, single-tool) produce a graph with a single node to avoid
  unnecessary overhead.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import anyio

from seahorse_ai.core.schemas import Message
from seahorse_ai.planner.hybrid_schemas import (
    DecompositionGraph,
    SubtaskNode,
)

logger = logging.getLogger(__name__)

DECOMPOSE_SYSTEM_PROMPT = """\
You are a task planner. Decompose the user's goal into a dependency graph of subtasks.

## Think Before Splitting
Ask yourself: "Does splitting this into multiple subtasks ACTUALLY help, or will one focused subtask get the same result faster?"
- If a single search or query can answer the entire goal → use 1 node.
- Only split when subtasks are genuinely INDEPENDENT and cover DIFFERENT data sources.
- Merging related work into fewer nodes is almost always better than splitting.

Output ONLY valid JSON:
{
  "goal": "string",
  "success_criteria": ["what defines a good answer"],
  "nodes": [{"id": "t1", "description": "string", "assigned_agent": "worker", "depends_on": []}]
}
"""


class TaskDecomposer:
    """Decompose a user goal into a dependency graph of subtasks."""

    def __init__(self, llm: Any) -> None:
        self._llm = llm

    async def decompose(
        self,
        goal: str,
        history: list[Message] | None = None,
        complexity: int = 3,
        skill_context: str | None = None,
    ) -> DecompositionGraph:
        """Return a dependency graph for the given goal.

        For simple goals (complexity <= 2) a single-node graph is returned
        without calling the LLM, saving ~1-3k tokens.
        """
        # Fast-Path: Skip LLM for most queries — single node is sufficient
        if complexity <= 3:
            return self._single_node_graph(goal)

        try:
            with anyio.fail_after(60):
                return await self._llm_decompose(
                    goal, history, skill_context, complexity=complexity
                )
        except TimeoutError:
            logger.warning("decomposer: LLM timed out — falling back to single node")
            return self._single_node_graph(goal)
        except Exception as exc:
            logger.error("decomposer: LLM failed: %s — falling back to single node", exc)
            return self._single_node_graph(goal)

    def _single_node_graph(self, goal: str) -> DecompositionGraph:
        return DecompositionGraph(
            goal=goal,
            success_criteria=[f"Provide a helpful answer to: {goal[:120]}"],
            nodes=[
                SubtaskNode(
                    id="t1",
                    description=goal,
                    assigned_agent="worker",
                    depends_on=[],
                )
            ],
        )

    async def _llm_decompose(
        self,
        goal: str,
        history: list[Message] | None,
        skill_context: str | None = None,
        complexity: int = 4,
    ) -> DecompositionGraph:
        context = ""
        if history:
            recent = history[-4:]
            context = "\n".join(f"{m.role}: {(m.content or '')[:200]}" for m in recent)

        user_msg = goal
        if context:
            user_msg = f"Recent context:\n{context}\n\nGoal: {goal}"

        system_prompt = DECOMPOSE_SYSTEM_PROMPT
        if skill_context:
            system_prompt = f"{DECOMPOSE_SYSTEM_PROMPT}\n\nACTIVE SKILL RULES:\n{skill_context}"

        messages = [
            Message(role="system", content=system_prompt),
            Message(role="user", content=user_msg),
        ]

        # Use fast tier — decomposition doesn't need expensive models
        tier = "fast"
        logger.info("decomposer: using tier=%s for complexity=%d", tier, complexity)
        result = await self._llm.complete(messages, tier=tier)
        raw = str(result.get("content", result) if isinstance(result, dict) else result)

        return self._parse_graph(raw, goal)

    def _parse_graph(self, raw: str, fallback_goal: str) -> DecompositionGraph:
        """Parse LLM JSON output into a DecompositionGraph, with fallback."""
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0]

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("decomposer: invalid JSON — falling back to single node")
            return self._single_node_graph(fallback_goal)

        nodes: list[SubtaskNode] = []
        for n in data.get("nodes", []):
            nodes.append(
                SubtaskNode(
                    id=n.get("id", f"t{len(nodes) + 1}"),
                    description=n.get("description", ""),
                    assigned_agent=n.get("assigned_agent", "worker"),
                    depends_on=n.get("depends_on", []),
                )
            )

        if not nodes:
            return self._single_node_graph(fallback_goal)

        return DecompositionGraph(
            goal=data.get("goal", fallback_goal),
            success_criteria=data.get("success_criteria", []),
            nodes=nodes,
        )
