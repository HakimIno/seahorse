"""seahorse_ai.planner.session_memory — 3-tier memory for the hybrid orchestrator.

Design decisions (from §5.4 of the design doc):

Tier 1 — Scratchpad (per-subagent, ephemeral)
    Lives inside the subagent's messages list.  Discarded after the subtask
    completes.  No explicit code needed here — it's the messages list itself.

Tier 2 — Structured KV (per-session, persist across iterations)
    Stores plan state, subtask status, and compressed result summaries.
    Implemented as an in-process dict keyed by ``session_id``.  Provides
    ``get_delta()`` for injecting only *what changed* since the last read.

Tier 3 — HNSW Vector (cross-session, long-term)
    Delegates to the existing ``seahorse_ai.tools.internal.memory`` RAG pipeline or
    the Rust-backed ``AgentMemory`` via FFI.  Only used for ``search()``
    before a replan to retrieve relevant past lessons.

Injection rule: total injected tokens ≤ 20% of context window.
"""

from __future__ import annotations

import logging
from typing import Any

from seahorse_ai.planner.hybrid_schemas import TrialArtifact

logger = logging.getLogger(__name__)

_DEFAULT_CONTEXT_WINDOW = 128_000
_CHARS_PER_TOKEN_ESTIMATE = 3.5


class SessionMemory:
    """Three-tier memory store scoped to a single orchestrator session."""

    def __init__(
        self,
        session_id: str,
        context_window_tokens: int = _DEFAULT_CONTEXT_WINDOW,
        tools: Any | None = None,
    ) -> None:
        self._session_id = session_id
        self._context_window = context_window_tokens
        self._tools = tools

        # Tier 2: structured KV — plan, artifacts, status
        self._kv: dict[str, Any] = {}
        self._trials: list[TrialArtifact] = []
        self._last_read_trial: int = -1

    @property
    def trials(self) -> list[TrialArtifact]:
        return self._trials

    # ── Tier 2: KV operations ─────────────────────────────────────────────────

    def put(self, key: str, value: Any) -> None:
        self._kv[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self._kv.get(key, default)

    def record_trial(self, artifact: TrialArtifact) -> None:
        self._trials.append(artifact)

    def get_delta(self) -> str:
        """Return a compressed summary of trials added since the last read.

        This is the key to preventing context burn: only the *new*
        information is injected, not the full history.
        """
        new_trials = self._trials[self._last_read_trial + 1 :]
        self._last_read_trial = len(self._trials) - 1

        if not new_trials:
            return ""

        parts: list[str] = []
        for t in new_trials:
            status_lines = []
            for sr in t.subtask_results:
                tag = "DONE" if not sr.terminated else f"FAIL({sr.termination_reason})"
                summary = sr.content[:300] if sr.content else "(empty)"
                status_lines.append(f"  - [{tag}] {sr.subtask_id}: {summary}")
            parts.append(
                f"Trial {t.trial_id} ({t.total_steps} steps, {t.total_ms}ms):\n"
                + "\n".join(status_lines)
            )

        return "\n".join(parts)

    def get_plan_summary(self) -> str:
        """Return the latest plan summary stored in KV, if any."""
        return str(self._kv.get("plan_summary", ""))

    # ── Tier 3: HNSW search (delegates to existing tools) ────────────────────

    async def search_relevant(self, query: str, top_k: int = 3) -> list[str]:
        """Semantic search for relevant past context via the RAG pipeline."""
        if not self._tools:
            return []

        try:
            raw = await self._tools.call(
                "memory_search",
                {"query": query, "agent_id": self._session_id, "top_k": top_k},
            )
            if isinstance(raw, list):
                return [str(r) for r in raw[:top_k]]
            return [str(raw)] if raw else []
        except Exception as exc:
            logger.warning("session_memory: HNSW search failed: %s", exc)
            return []

    # ── Context injection ─────────────────────────────────────────────────────

    def build_context_block(
        self,
        subtask_description: str,
        goal: str,
        success_criteria: list[str],
        tier3_results: list[str] | None = None,
    ) -> str:
        """Compose the context block injected before each subagent run.

        Enforces the ≤20% of context window rule.
        """
        max_chars = int(
            self._context_window * _CHARS_PER_TOKEN_ESTIMATE * self._memory_inject_ratio
        )

        parts: list[str] = []
        parts.append(f"## Goal\n{goal}")
        if success_criteria:
            parts.append(
                "## Success Criteria\n" + "\n".join(f"- {c}" for c in success_criteria)
            )
        parts.append(f"## Current Subtask\n{subtask_description}")

        delta = self.get_delta()
        if delta:
            parts.append(f"## Previous Trial Results (delta)\n{delta}")

        if tier3_results:
            parts.append(
                "## Relevant Past Context\n" + "\n".join(f"- {r}" for r in tier3_results)
            )

        block = "\n\n".join(parts)

        if len(block) > max_chars:
            block = block[:max_chars] + "\n...(truncated to fit 20% window limit)"
            logger.info(
                "session_memory: context block truncated to %d chars (limit=%d)",
                len(block),
                max_chars,
            )

        return block

    @property
    def _memory_inject_ratio(self) -> float:
        return 0.20

    # ── Tier 3: persist summary to HNSW for cross-session learning ───────────

    async def persist_lesson(self, lesson: str) -> None:
        """Store a lesson-learned in HNSW for future sessions."""
        if not self._tools or not lesson.strip():
            return
        try:
            await self._tools.call(
                "memory_store",
                {
                    "text": lesson,
                    "importance": 4,
                    "agent_id": self._session_id,
                },
            )
        except Exception as exc:
            logger.warning("session_memory: persist_lesson failed: %s", exc)
