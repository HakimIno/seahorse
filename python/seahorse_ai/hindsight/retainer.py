"""seahorse_ai.hindsight.retainer — The Retain Operation.

Responsible for extracting high-fidelity HindsightRecords from raw text
and persisting them to multi-modal storage.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from seahorse_ai.llm import get_llm
from seahorse_ai.schemas import Message
from .models import HindsightRecord, MemoryCategory, Entity, Relation, TemporalContext

logger = logging.getLogger(__name__)

_RETAIN_PROMPT = """\
<system>
You are a Hindsight Memory Extractor. Extract structured facts from the <input_text>.
</system>

<instructions>
1. Identify entities (People, Places, Objects) and their relationships.
2. Determine if the fact is a WORLD truth (general knowledge) or an EXPERIENCE (specific event/interaction).
3. Extract temporal context (e.g., "yesterday", "5 years ago").
4. Return a JSON array of records.
</instructions>

<input_text>
{text}
</input_text>

<output_format>
[
  {{
    "text": "Self-contained fact sentence",
    "category": "WORLD|EXPERIENCE|MENTAL_MODEL",
    "importance": 1-5,
    "entities": [{{ "name": "Alice", "type": "PERSON" }}],
    "relations": [{{ "subject": "Alice", "predicate": "likes", "object": "Sushi" }}],
    "temporal": {{ "relative_description": "yesterday" }}
  }}
]
</output_format>
"""

class HindsightRetainer:
    def __init__(self, pipeline: Any) -> None:
        """Initialize with a storage pipeline."""
        self.pipeline = pipeline
        self.llm = get_llm("worker")

    async def retain(self, text: str, agent_id: str | None = None) -> list[HindsightRecord]:
        """Process text and store extracted records with cost optimization."""
        
        # 1. Fast Path Optimization: For short/trivial text, avoid LLM call
        if len(text.strip()) < 40:
            logger.info("Hindsight: Fast Path Retain (text too short for deep extraction)")
            record = HindsightRecord(
                text=text.strip(),
                category=MemoryCategory.EXPERIENCE,
                agent_id=agent_id,
                metadata={"extraction_mode": "fast_path"}
            )
            await self.pipeline.store(
                record.text,
                metadata=record.to_qdrant_payload(),
                agent_id=agent_id
            )
            return [record]

        # 2. Deep Path: XML-Based Extraction
        prompt = _RETAIN_PROMPT.format(text=text)
        
        try:
            logger.info("Hindsight: Deep Path Retain (LLM Extraction) len=%d", len(text))
            result = await self.llm.complete([Message(role="user", content=prompt)], tier="worker")
            raw = str(result.get("content", result) if isinstance(result, dict) else result).strip()
            
            # Fail-Safe Parsing: Extract JSON block
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0].strip()
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0].strip()
            elif "[" in raw and "]" in raw:
                # Fallback: find first [ and last ]
                start = raw.find("[")
                end = raw.rfind("]") + 1
                raw = raw[start:end]
                
            data = json.loads(raw)
            records: list[HindsightRecord] = []
            
            for item in data:
                # Struct validation via msgspec in models
                record = HindsightRecord(
                    text=item["text"],
                    category=MemoryCategory(item.get("category", "EXPERIENCE")),
                    importance=item.get("importance", 3),
                    agent_id=agent_id,
                    metadata={"extraction_mode": "deep_path"}
                )
                
                # Hydrate entities
                for e in item.get("entities", []):
                    record.entities.append(Entity(name=e["name"], type=e.get("type", "GENERIC")))
                
                # Hydrate relations
                for r in item.get("relations", []):
                    record.relations.append(Relation(subject=r["subject"], predicate=r["predicate"], object=r["object"]))
                
                # Hydrate temporal
                t_hint = item.get("temporal", {})
                record.temporal.relative_description = t_hint.get("relative_description")
                
                records.append(record)
                
                # 3. Persistence with Semantic Deduplication
                # Check if a very similar fact already exists to avoid redundancy
                existing = await self.pipeline.search(
                    record.text,
                    k=1,
                    filter_metadata={"agent_id": agent_id} if agent_id else None
                )
                
                if existing and existing[0].get("distance", 1.0) < 0.05:
                    logger.info("Hindsight: Skipping redundant record (dist=%.4f)", existing[0]["distance"])
                    continue

                await self.pipeline.store(
                    record.text,
                    metadata=record.to_qdrant_payload(),
                    agent_id=agent_id,
                    importance=record.importance
                )
                
            return records

        except Exception as e:
            logger.error(f"Hindsight Retain failed: {e}")
            # Final Fallback: store raw text
            await self.pipeline.store(text, agent_id=agent_id, metadata={"error": str(e)})
            return []
