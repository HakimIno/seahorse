import anyio
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
        """Initialize parameters for tracking consecutive and per-tool errors."""
        self._consecutive_errors: int = 0
        self._tool_errors: dict[str, int] = {}

    # ── Public API ─────────────────────────────────────────────────────────────

    def record_success(self) -> None:
        """Reset consecutive error counter after any successful tool call."""
        self._consecutive_errors = 0

    async def record_error(self, tool_name: str | None, is_crash: bool = False) -> None:
        """Record a tool error. Increments both global and per-tool counters."""
        self._consecutive_errors += 1
        if tool_name:
            self._tool_errors[tool_name] = self._tool_errors.get(tool_name, 0) + 1

        # Track globally as well via FFI
        await record_global_failure()

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
        """Return global consecutive error count."""
        return self._consecutive_errors


async def record_global_failure() -> None:
    """Increment global failure counter via FFI."""
    try:
        import seahorse_ffi

        await anyio.to_thread.run_sync(seahorse_ffi.record_global_failure)
    except ImportError:
        logger.warning("seahorse_ffi not found. Global Circuit Breaker ignored.")
    except Exception as e:
        logger.error("Global Circuit Breaker: Failed to record failure FFI: %s", e)


async def is_system_healthy() -> bool:
    """Check if the global circuit breaker has tripped via FFI."""
    try:
        import seahorse_ffi

        healthy = await anyio.to_thread.run_sync(seahorse_ffi.is_system_healthy)
        if not healthy:
            logger.critical("Global Circuit Breaker TRIPPED via FFI.")
        return healthy
    except ImportError:
        return True
    except Exception as e:
        logger.error("Global Circuit Breaker: Failed to check health FFI: %s", e)
        return True
