"""seahorse_ai.router — Semantic routing of LLM requests to specialized models."""
from __future__ import annotations

import logging
from typing import Literal

from seahorse_ai.llm import LLMClient
from seahorse_ai.schemas import LLMConfig, Message

logger = logging.getLogger(__name__)

ModelTier = Literal["worker", "thinker", "strategist", "fast"]

class ModelRouter:
    """Routes requests to specialized models based on task complexity."""
    
    def __init__(
        self, 
        worker_model: str, 
        thinker_model: str, 
        strategist_model: str,
        fast_path_model: str | None = None
    ) -> None:
        self.worker = LLMClient(config=LLMConfig(model=worker_model))
        self.thinker = LLMClient(config=LLMConfig(model=thinker_model))
        self.strategist = LLMClient(config=LLMConfig(model=strategist_model))
        # Default to worker if fast_path_model not provided
        self.fast = LLMClient(config=LLMConfig(
            model=fast_path_model or "openrouter/google/gemini-2.0-flash-lite-preview-02-05"
        ))
        
    async def complete(
        self, messages: list[Message], tier: ModelTier = "worker", **kwargs: object
    ) -> str | dict[str, object]:
        """Execute a completion using the specified model tier."""
        client = getattr(self, tier)
        logger.info(f"Routing request to {tier} model: {client._config.model}")
        return await client.complete(messages, **kwargs)

    async def classify_intent(self, prompt: str) -> ModelTier:
        """Determines the required model tier based on prompt keywords and complexity."""
        p = prompt.lower()
        
        # Level 0: Fast Lock (Greetings & Casual Talk)
        # Use 'fast' tier (gemini-3.1-flash-lite) for extreme cost efficiency
        from seahorse_ai.prompts.intent import _is_greeting
        if _is_greeting(p):
            logger.info("Fast Lock: Greeting detected. Routing to 'fast' tier.")
            return "fast"

        # Level 1: Budget Lock (Simple short queries)
        if len(p.split()) < 5:
            logger.info("Budget Lock: Very short query detected. Routing to 'fast' tier.")
            return "fast"

        # Level 4: Strategist (Creative/Business Summary)
        strategy_kws = [
            "สรุป", "แนะนำ", "กลยุทธ์", "แนวคิด", "ไอเดีย", "แผนการ", "รับมือ", "forecast",
            "summary", "recommend", "strategy", "idea", "plan", "future", "trend"
        ]
        if any(kw in p for kw in strategy_kws):
            return "strategist"
            
        # Level 3: Thinker (Complex logic/Comparison)
        logic_kws = [
            "เปรียบเทียบ", "วิเคราะห์", "เพราะอะไร", "ทำไม", "แตกต่าง", "ดีกว่า",
            "compare", "analyze", "why", "complex", "difference", "better", "versus", "vs"
        ]
        if any(kw in p for kw in logic_kws):
            return "thinker"
            
        # Default to level 2: Worker (Data extraction/SQL/Simple facts)
        return "worker"
