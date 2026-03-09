import logging
import os
import json
import time

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
        
        # Track globally as well
        import asyncio
        asyncio.create_task(record_global_failure())

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


async def record_global_failure() -> None:
    """Increment global failure counter in Postgres."""
    import asyncpg
    pg_uri = os.environ.get("SEAHORSE_PG_URI")
    if not pg_uri:
        return

    try:
        conn = await asyncpg.connect(pg_uri)
        try:
            # Atomic increment and status update
            await conn.execute("""
                UPDATE seahorse_system_status 
                SET value = jsonb_set(
                    jsonb_set(value, '{fail_count}', ((value->>'fail_count')::int + 1)::text::jsonb),
                    '{last_fail}', to_jsonb(EXTRACT(EPOCH FROM NOW()))
                )
                WHERE key = 'circuit_breaker';
            """)
        finally:
            await conn.close()
    except Exception as e:
        logger.error("Global Circuit Breaker: Failed to record failure: %s", e)


async def is_system_healthy() -> bool:
    """Check if the global circuit breaker has tripped."""
    import asyncpg
    pg_uri = os.environ.get("SEAHORSE_PG_URI")
    if not pg_uri:
        return True

    try:
        conn = await asyncpg.connect(pg_uri)
        try:
            row = await conn.fetchrow("SELECT value FROM seahorse_system_status WHERE key = 'circuit_breaker';")
            if not row:
                return True
            
            val = row['value']
            if isinstance(val, str):
                val = json.loads(val)
            
            fail_count = val.get('fail_count', 0)
            last_fail = val.get('last_fail')
            
            # Trip if more than 5 failures in the last 60 seconds
            if fail_count >= 5 and last_fail:
                now = time.time()
                if now - last_fail < 60:
                    logger.critical("Global Circuit Breaker TRIPPED (fail_count=%d)", fail_count)
                    return False
                else:
                    # Auto-reset if old
                    await conn.execute("UPDATE seahorse_system_status SET value = '{\"status\": \"CLOSED\", \"fail_count\": 0, \"last_fail\": null}' WHERE key = 'circuit_breaker';")
            
            return True
        finally:
            await conn.close()
    except Exception as e:
        logger.error("Global Circuit Breaker: Failed to check health: %s", e)
        return True
