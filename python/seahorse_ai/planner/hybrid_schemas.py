"""seahorse_ai.planner.hybrid_schemas — Data types for the Hybrid Agent pattern.

Orchestrator → parallel Subagents → Critic → 3-tier Memory.

All types are msgspec Structs for zero-copy serialization and compatibility
with the existing Seahorse schema conventions.
"""

from __future__ import annotations

from msgspec import Struct, field

# ── Goal & Success Criteria ───────────────────────────────────────────────────


class GoalSpec(Struct, omit_defaults=True):
    """User-level goal with explicit success criteria."""

    goal: str
    success_criteria: list[str] = field(default_factory=list)


# ── Dependency Graph (Decomposer output) ─────────────────────────────────────


class SubtaskNode(Struct, omit_defaults=True):
    """A single subtask in the dependency graph.

    ``depends_on`` lists ids of subtasks that must finish before this one
    can start.  An empty list means the subtask is independent and can
    run in parallel with other independent nodes.
    """

    id: str
    description: str
    assigned_agent: str = "worker"
    depends_on: list[str] = field(default_factory=list)
    status: str = "pending"
    result_summary: str | None = None


class DecompositionGraph(Struct, omit_defaults=True):
    """Output of the task decomposer — a DAG of subtasks."""

    goal: str
    nodes: list[SubtaskNode] = field(default_factory=list)
    success_criteria: list[str] = field(default_factory=list)

    def ready_nodes(self) -> list[SubtaskNode]:
        """Return subtasks whose dependencies are all satisfied."""
        done_ids = {n.id for n in self.nodes if n.status == "done"}
        return [
            n
            for n in self.nodes
            if n.status == "pending" and all(d in done_ids for d in n.depends_on)
        ]

    def all_done(self) -> bool:
        return all(n.status in ("done", "skipped") for n in self.nodes)

    def get_node(self, node_id: str) -> SubtaskNode | None:
        for n in self.nodes:
            if n.id == node_id:
                return n
        return None


# ── Trial Artifact (Persist layer) ───────────────────────────────────────────


class SubtaskResult(Struct, omit_defaults=True):
    """Compressed result of a single subagent execution."""

    subtask_id: str
    content: str
    steps: int = 0
    terminated: bool = False
    termination_reason: str | None = None
    tool_names_used: list[str] = field(default_factory=list)


class TrialArtifact(Struct, omit_defaults=True):
    """Snapshot of one trial's execution — stored in Tier 2 KV memory."""

    trial_id: int
    plan_summary: str
    subtask_results: list[SubtaskResult] = field(default_factory=list)
    total_steps: int = 0
    total_ms: int = 0


# ── Critic Verdict ────────────────────────────────────────────────────────────


class CriticVerdict(Struct, omit_defaults=True):
    """Three-level verdict from the isolated critic.

    - ``pass``: all criteria met → return to user.
    - ``partial``: some criteria met → targeted replan on ``failed_subtasks``.
    - ``reject``: output fundamentally wrong → full replan.
    """

    verdict: str  # "pass" | "partial" | "reject"
    passed_criteria: list[str] = field(default_factory=list)
    failed_criteria: list[str] = field(default_factory=list)
    failed_subtasks: list[str] = field(default_factory=list)
    reason: str = ""


# ── Orchestrator Config ──────────────────────────────────────────────────────


class HybridConfig(Struct, omit_defaults=True):
    """Tuning knobs for the hybrid orchestrator."""

    max_trials: int = 3
    max_steps_per_subtask: int = 10
    step_timeout_seconds: int = 120
    global_timeout_seconds: int = 600
    memory_inject_ratio: float = 0.20
    use_llm_critic: bool = True
