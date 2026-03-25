"""seahorse_ai.core.router — Semantic routing of LLM requests to specialized models."""

from __future__ import annotations
from collections.abc import AsyncIterator

import logging
from typing import Literal

from seahorse_ai.core.llm import LLMClient
from seahorse_ai.core.schemas import LLMConfig, Message
from seahorse_ai.prompts.intent import _is_greeting

logger = logging.getLogger(__name__)

ModelTier = Literal["worker", "thinker", "strategist", "fast"]


class ModelRouter:
    """Routes requests to specialized models based on task complexity."""

    def __init__(
        self,
        worker_model: str,
        thinker_model: str,
        strategist_model: str,
        fast_path_model: str | None = None,
    ) -> None:
        # Create LLMConfig instances with appropriate model fields
        self.worker = LLMClient(config=LLMConfig(worker_model=worker_model))
        self.thinker = LLMClient(config=LLMConfig(thinker_model=thinker_model))
        self.strategist = LLMClient(config=LLMConfig(strategist_model=strategist_model))
        # Default to worker config if fast_path_model not provided
        self.fast = (
            LLMClient(config=LLMConfig(fast_path_model=fast_path_model)) if fast_path_model else self.worker
        )

    async def complete(
        self, messages: list[Message], tier: ModelTier = "worker", **kwargs: object
    ) -> str | dict[str, object]:
        """Execute a completion using the specified model tier."""
        client = getattr(self, tier)
        return await client.complete(messages, tier=tier, **kwargs)

    def stream(
        self, messages: list[Message], tier: ModelTier = "worker", **kwargs: object
    ) -> AsyncIterator[str]:
        """Stream tokens from the specified model tier."""
        client = getattr(self, tier)
        return client.stream(messages, tier=tier, **kwargs)

    async def classify_intent(self, prompt: str) -> ModelTier:
        """Determines the required model tier based on prompt keywords and complexity."""
        p = prompt.lower()

        if _is_greeting(p) or len(p.split()) <= 2:
            logger.info("Short-circuit: Fast tier selected for minimal prompt.")
            return "fast"

        # Level 4: Strategist (Creative/Business Summary)
        strategy_kws = [
            "สรุป",
            "แนะนำ",
            "กลยุทธ์",
            "แนวคิด",
            "ไอเดีย",
            "แผนการ",
            "รับมือ",
            "forecast",
            "summary",
            "recommend",
            "strategy",
            "idea",
            "plan",
            "future",
            "trend",
        ]
        if any(kw in p for kw in strategy_kws):
            return "strategist"

        # Level 3: Thinker (Complex logic/Comparison)
        logic_kws = [
            "เปรียบเทียบ",
            "วิเคราะห์",
            "เพราะอะไร",
            "ทำไม",
            "แตกต่าง",
            "ดีกว่า",
            "compare",
            "analyze",
            "why",
            "complex",
            "difference",
            "better",
            "versus",
            "vs",
        ]
        if any(kw in p for kw in logic_kws):
            return "thinker"

        # Default to level 2: Worker (Data extraction/SQL/Simple facts)
        return "worker"
