"""seahorse_ai.router — Semantic routing of LLM requests to specialized models."""
from __future__ import annotations

import logging
from typing import Literal

from seahorse_ai.llm import LLMClient
from seahorse_ai.schemas import LLMConfig, Message

logger = logging.getLogger(__name__)

ModelTier = Literal["worker", "thinker", "strategist"]

class ModelRouter:
    """Routes requests to specialized models based on task complexity."""
    
    def __init__(self, worker_model: str, thinker_model: str, strategist_model: str) -> None:
        self.worker = LLMClient(config=LLMConfig(model=worker_model))
        self.thinker = LLMClient(config=LLMConfig(model=thinker_model))
        self.strategist = LLMClient(config=LLMConfig(model=strategist_model))
        
    async def complete(
        self, messages: list[Message], tier: ModelTier = "worker", **kwargs: object
    ) -> str | dict[str, object]:
        """Execute a completion using the specified model tier."""
        client = getattr(self, tier)
        logger.info(f"Routing request to {tier} model: {client._config.model}")
        return await client.complete(messages, **kwargs)

    def classify_intent(self, prompt: str) -> ModelTier:
        """Determines the required model tier based on prompt keywords and complexity."""
        p = prompt.lower()
        
        # Level 1: Budget Lock (Simple Greetings & Casual Talk)
        greetings = [
            "hi", "hello", "สวัสดี", "หวัดดี", "ทักทาย", "hey", "โย่", "วันนี้วันอะไร", "กี่โมง"
        ]
        if any(kw in p for kw in greetings) and len(p.split()) < 10:
            logger.info("Budget Lock: Simple intent detected. Locking to worker tier.")
            return "worker"

        # Level 4: Strategist (Creative/Business Summary)
        strategy_kws = [
            "สรุป", "แนะนำ", "กลยุทธ์", "แนวคิด", "ไอเดีย", "summary", "recommend", "strategy", "idea"
        ]
        if any(kw in p for kw in strategy_kws):
            return "strategist"
            
        # Level 3: Thinker (Complex logic/Comparison)
        logic_kws = [
            "เปรียบเทียบ", "วิเคราะห์", "เพราะอะไร", "ทำไม", "compare", "analyze", "why", "complex"
        ]
        if any(kw in p for kw in logic_kws):
            return "thinker"
            
        # Default to level 2: Worker (Data extraction/SQL)
        return "worker"
