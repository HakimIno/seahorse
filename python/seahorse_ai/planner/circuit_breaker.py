"""seahorse_ai.planner.circuit_breaker — Error tracking and termination logic.

Tracks consecutive errors and tool-specific failure counts.
Provides a clean interface to decide when the agent should terminate.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """Track tool errors and decide when to terminate the agent loop.

    Design:
    - Consecutive errors > threshold → terminate (too many back-to-back)
    - Tool-specific errors > 2 → self-correction nudge injected
    - SYSTEM_CRASH in observation → immediate terminate
    """

    CONSECUTIVE_ERROR_LIMIT: int = 3
    TOOL_ERROR_NUDGE_THRESHOLD: int = 2

    def __init__(self) -> None:
        self._consecutive_errors: int = 0
        self._tool_errors: dict[str, int] = {}

    # ── Public API ─────────────────────────────────────────────────────────────

    def record_success(self) -> None:
        """Reset consecutive error counter after any successful tool call."""
        self._consecutive_errors = 0

    def record_error(self, tool_name: str | None, is_crash: bool = False) -> None:
        """Record a tool error. Increments both global and per-tool counters."""
        self._consecutive_errors += 1
        if tool_name:
            self._tool_errors[tool_name] = self._tool_errors.get(tool_name, 0) + 1
        if is_crash:
            logger.error("circuit_breaker: SYSTEM_CRASH in tool=%s", tool_name)

    def should_terminate(self) -> tuple[bool, str]:
        """Return (should_terminate, reason). Empty reason means no termination."""
        if self._consecutive_errors >= self.CONSECUTIVE_ERROR_LIMIT:
            return True, (
                f"[TERMINATED] {self._consecutive_errors} consecutive tool errors. "
                "Stopping to prevent wasting tokens."
            )
        return False, ""

    def get_nudge(self, tool_name: str | None, observation: str) -> str:
        """Return an injected self-correction nudge if a tool is failing repeatedly."""
        if tool_name and self._tool_errors.get(tool_name, 0) >= self.TOOL_ERROR_NUDGE_THRESHOLD:
            logger.warning("circuit_breaker: self-correction nudge for tool=%s", tool_name)
            return (
                f"{observation}\n\n[SYSTEM: You have failed to use {tool_name!r} "
                "correctly 2+ times. Please STOP and try a completely different approach.]"
            )
        return observation

    @property
    def consecutive_errors(self) -> int:
        return self._consecutive_errors
