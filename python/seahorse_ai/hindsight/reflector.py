"""seahorse_ai.hindsight.reflector — The Reflect Operation.

Synthesizes Mental Models (insights) from raw Experiences.
Helps the AI "learn" patterns over time.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from seahorse_ai.core.llm import get_llm
from seahorse_ai.core.schemas import Message
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
        """Fetch experiences and synthesize new mental models."""
        
        # 1. Fetch recent experiences
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
            
            data = self._parse_llm_json(raw)
            new_models: list[HindsightRecord] = []
            
            for item in data:
                model = HindsightRecord(
                    text=item["text"],
                    category=MemoryCategory.MENTAL_MODEL,
                    importance=item.get("importance", 4),
                    agent_id=agent_id,
                    metadata={"confidence": item.get("confidence", 0.8), "source": "reflection"}
                )
                
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

    async def consolidate_wisdom(self, agent_id: str | None = None) -> list[HindsightRecord]:
        """Review existing Mental Models and consolidate them into high-level Wisdom."""
        
        # 1. Fetch existing mental models
        models = await self.pipeline.search(
            "", 
            k=25, 
            filter_metadata={
                "agent_id": agent_id,
                "category": MemoryCategory.MENTAL_MODEL.value
            } if agent_id else {"category": MemoryCategory.MENTAL_MODEL.value}
        )
        
        if len(models) < 5:
            return []

        logger.info("Hindsight: Consolidating %d mental models into wisdom...", len(models))
        models_text = "\n".join([f"- {m['text']}" for m in models])
        
        prompt = f"""\
<system>
You are the Hindsight Wisdom Consolidator. Your goal is to merge specific Mental Models into comprehensive, universal Wisdom records.
</system>

<instructions>
1. Review the provided <mental_models>.
2. Group similar or related rules together.
3. Resolve any contradictions by preferring the most logical or common pattern.
4. Synthesize them into 1-2 powerful "Wisdom" observations.
</instructions>

<mental_models>
{models_text}
</mental_models>

<output_format>
[
  {{
    "text": "The consolidated wisdom record",
    "importance": 5,
    "confidence": 0.9
  }}
]
</output_format>
"""
        try:
            result = await self.llm.complete([Message(role="user", content=prompt)], tier="worker")
            raw = str(result.get("content", result) if isinstance(result, dict) else result).strip()
            
            data = self._parse_llm_json(raw)
            wisdom_records: list[HindsightRecord] = []
            
            for item in data:
                wisdom = HindsightRecord(
                    text=item["text"],
                    category=MemoryCategory.WISDOM,
                    importance=item.get("importance", 5),
                    agent_id=agent_id,
                    metadata={"confidence": item.get("confidence", 0.9), "source": "wisdom_consolidation"}
                )
                
                await self.pipeline.store(
                    wisdom.text,
                    metadata=wisdom.to_qdrant_payload(),
                    agent_id=agent_id,
                    importance=wisdom.importance
                )
                wisdom_records.append(wisdom)
                
            return wisdom_records
        except Exception as e:
            logger.error(f"Hindsight Wisdom Consolidation failed: {e}")
            return []

    def _parse_llm_json(self, raw: str) -> list[dict[str, Any]]:
        """Extract and parse JSON results from LLM output."""
        try:
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0].strip()
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0].strip()
            
            start_list = raw.find("[")
            start_dict = raw.find("{")
            
            if start_list != -1 and (start_dict == -1 or start_list < start_dict):
                end = raw.rfind("]") + 1
                raw = raw[start_list:end]
            elif start_dict != -1:
                end = raw.rfind("}") + 1
                raw = raw[start_dict:end]
                
            data = json.loads(raw)
            return data if isinstance(data, list) else [data]
        except Exception:
            logger.warning("Hindsight: Failed to parse LLM JSON: %s", raw[:100])
            return []
