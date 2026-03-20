"""seahorse_ai.planner.strategy — Strategy plan generation with LRU caching.

Generates a master plan before execution using a high-tier LLM.
Caches results by prompt hash to avoid redundant API calls for similar queries.

Phase 2: Strategy Caching
  - Key: MD5 of first 200 chars of prompt
  - TTL: 5 minutes
  - Max entries: 256
"""

from __future__ import annotations

import hashlib
import logging
import time

from seahorse_ai.prompts import STRATEGY_GENERATION_PROMPT, STRATEGY_NUDGE
from seahorse_ai.schemas import Message

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS: float = 300.0  # 5 minutes
_MAX_CACHE_SIZE: int = 256


class StrategyPlanner:
    """Generate strategy plans, with caching to reduce LLM cost.

    A strategy plan is a 3-5 bullet roadmap injected before the ReAct loop
    to guide the agent in selecting the right tools and order of operations.
    """

    def __init__(self, llm: object) -> None:
        self._llm = llm
        # Cache: {hash: (plan_text, created_at)}
        self._cache: dict[str, tuple[str, float]] = {}

    async def plan(self, prompt: str, complexity: int = 4) -> str:
        """Return a strategy plan for the prompt. Uses cache if available.

        Args:
            prompt: The user's original prompt.
            complexity: 1-5 scale. Determines which LLM tier to use:
                        - 4-5: strategist (expensive, highest quality)
                        - 3:   thinker   (medium cost, good quality)
                        - 1-2: skipped entirely (no plan generated)
        """
        key = self._hash(prompt)

        # Check cache (with TTL)
        if key in self._cache:
            plan, created_at = self._cache[key]
            if time.monotonic() - created_at < _CACHE_TTL_SECONDS:
                logger.info("strategy.plan: cache hit (age=%.1fs)", time.monotonic() - created_at)
                return plan
            else:
                del self._cache[key]

        # Evict oldest entry if at capacity
        if len(self._cache) >= _MAX_CACHE_SIZE:
            oldest = min(self._cache, key=lambda k: self._cache[k][1])
            del self._cache[oldest]

        # Generate fresh plan — tier depends on complexity
        tier = "strategist" if complexity >= 4 else "thinker"
        plan = await self._generate(prompt, tier=tier)
        self._cache[key] = (plan, time.monotonic())
        logger.info("strategy.plan: generated (tier=%s) and cached (cache_size=%d)", tier, len(self._cache))
        return plan

    def nudge_message(self) -> Message:
        """Return the system message that attaches the strategy plan to the conversation."""
        return Message(role="system", content=STRATEGY_NUDGE)

    def invalidate(self, prompt: str) -> None:
        """Manually invalidate a cached plan (e.g. after user corrects data)."""
        key = self._hash(prompt)
        self._cache.pop(key, None)

    @property
    def cache_size(self) -> int:
        return len(self._cache)

    # ── Private ────────────────────────────────────────────────────────────────

    @staticmethod
    def _hash(prompt: str) -> str:
        return hashlib.md5(prompt[:200].encode()).hexdigest()

    async def _generate(self, prompt: str, tier: str = "strategist") -> str:
        """Call LLM to generate a fresh strategy plan."""
        messages = [
            Message(role="system", content=STRATEGY_GENERATION_PROMPT),
            Message(role="user", content=prompt),
        ]
        try:
            result = await self._llm.complete(messages, tier=tier)  # type: ignore[union-attr]
            text = str(result.get("content", result) if isinstance(result, dict) else result)
            logger.info("strategy._generate: plan generated (tier=%s, %d chars)", tier, len(text))
            return text
        except Exception as exc:  # noqa: BLE001
            logger.error("strategy._generate: failed: %s", exc)
            return "[STRATEGY PLAN]\n- Proceed with standard ReAct loop."
