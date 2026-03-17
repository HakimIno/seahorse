"""seahorse_ai.hindsight.reflector — The Reflect Operation.

Synthesizes Mental Models (insights) from raw Experiences.
Helps the AI "learn" patterns over time.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from seahorse_ai.llm import get_llm
from seahorse_ai.schemas import Message
from .models import HindsightRecord, MemoryCategory

logger = logging.getLogger(__name__)

_REFLECT_PROMPT = """\
<system>
You are the Hindsight Memory Synthesizer. Your goal is to convert raw Experiences into long-term Mental Models.
</system>

<instructions>
1. Analyze the provided <experiences>.
2. Identify stable patterns, user preferences, or recurring facts.
3. Synthesize them into 1-2 distinct MENTAL MODELS.
4. Avoid redundant insights. Resolve any conflicting information based on the most recent data.
</instructions>

<experiences>
{experiences_text}
</experiences>

<output_format>
[
  {{
    "text": "The synthesized insight or general rule",
    "importance": 4,
    "confidence": 0.8
  }}
]
</output_format>
"""

class HindsightReflector:
    def __init__(self, pipeline: Any) -> None:
        self.pipeline = pipeline
        self.llm = get_llm("worker")

    async def reflect(self, agent_id: str | None = None, k_experiences: int = 50) -> list[HindsightRecord]:
        """Fetch experiences and synthesize new mental models with optimization."""
        
        # 1. Fetch recent experiences
        # Threshold: Increased to 10 for better synthesis quality
        experiences = await self.pipeline.search(
            "", 
            k=k_experiences, 
            filter_metadata={
                "agent_id": agent_id,
                "category": MemoryCategory.EXPERIENCE.value
            } if agent_id else {"category": MemoryCategory.EXPERIENCE.value}
        )
        
        if len(experiences) < 10:
            logger.info("Hindsight: Not enough experiences to reflect (need 10, have %d).", len(experiences))
            return []

        logger.info("Hindsight: Reflecting on %d experiences...", len(experiences))
        exp_text = "\n".join([f"- {e['text']}" for e in experiences])
        prompt = _REFLECT_PROMPT.format(experiences_text=exp_text)
        
        try:
            result = await self.llm.complete([Message(role="user", content=prompt)], tier="worker")
            raw = str(result.get("content", result) if isinstance(result, dict) else result).strip()
            
            # Fail-Safe Parsing
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0].strip()
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0].strip()
            elif "[" in raw and "]" in raw:
                start = raw.find("[")
                end = raw.rfind("]") + 1
                raw = raw[start:end]
                
            data = json.loads(raw)
            new_models: list[HindsightRecord] = []
            
            for item in data:
                model = HindsightRecord(
                    text=item["text"],
                    category=MemoryCategory.MENTAL_MODEL,
                    importance=item.get("importance", 4),
                    agent_id=agent_id,
                    metadata={"confidence": item.get("confidence", 0.8), "source": "reflection"}
                )
                
                # Persistence
                await self.pipeline.store(
                    model.text,
                    metadata=model.to_qdrant_payload(),
                    agent_id=agent_id,
                    importance=model.importance
                )
                new_models.append(model)
                
            logger.info(f"Hindsight: Reflect synthesized {len(new_models)} mental models.")
            return new_models

        except Exception as e:
            logger.error(f"Hindsight Reflect failed: {e}")
            return []
