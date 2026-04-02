"""seahorse_ai.hindsight.retainer — The Retain Operation.

Responsible for extracting high-fidelity HindsightRecords from raw text
and persisting them to multi-modal storage.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from datetime import UTC, datetime, timedelta
from typing import Any

from seahorse_ai.core.llm import get_llm
from seahorse_ai.core.schemas import Message
from seahorse_ai.engines.graph_db import GraphManager

from .models import Entity, HindsightRecord, MemoryCategory, Relation

logger = logging.getLogger(__name__)

_RETAIN_PROMPT = """\
<system>Extract structured facts from <input_text>. Skip if no facts found.</system>
<input_text>{text}</input_text>
<output_format>
[
  {{
    "text": "Fact sentence",
    "category": "WORLD|EXPERIENCE|MENTAL_MODEL",
    "importance": 1-5,
    "entities": [{{ "name": "...", "type": "..." }}],
    "relations": [{{ "subject": "...", "predicate": "...", "object": "..." }}]
  }}
]
</output_format>
"""


class HindsightRetainer:
    def __init__(self, pipeline: Any, concurrency: int = 5) -> None:
        """Initialize with a storage pipeline and concurrency control."""
        self.pipeline = pipeline
        self.llm = get_llm("worker")
        self.graph = GraphManager()
        self.semaphore = asyncio.Semaphore(concurrency)

    def _repair_json(self, raw: str) -> str:
        """Attempt to fix common LLM JSON errors like single quotes."""
        # Replace single quotes with double quotes (rough heuristic)
        # This is dangerous for text containing apostrophes, so we only do it if normal parse fails
        import re

        # Fix single quotes around keys
        raw = re.sub(r"([{,])\s*'([^']+)':", r'\1"\2":', raw)
        # Fix single quotes around values
        raw = re.sub(r":\s*'([^']*)'([,}])", r': "\1"\2', raw)
        return raw

    async def retain(
        self, text: str, agent_id: str | None = None, importance: int | None = None
    ) -> list[HindsightRecord]:
        """Process text and store extracted records with cost and concurrency optimization."""
        async with self.semaphore:
            return await self._retain_internal(text, agent_id, importance)

    async def retain_batch(
        self, texts: list[str], agent_id: str | None = None, importance: int | None = None
    ) -> list[HindsightRecord]:
        """Process multiple texts in parallel using the internal semaphore."""
        logger.info("Hindsight: Processing batch of %d records...", len(texts))
        tasks = [self.retain(text, agent_id, importance) for text in texts]
        results = await asyncio.gather(*tasks)
        # Flatten results
        all_records = [rec for sublist in results for rec in sublist]
        return all_records

    async def _retain_internal(
        self, text: str, agent_id: str | None = None, importance: int | None = None
    ) -> list[HindsightRecord]:
        """The core retention logic with high-performance Tiered Processing."""

        # Tier 1: Fast Path Optimization (Threshold: 150 chars)
        # Avoid LLM for short facts / simple key-values
        if len(text.strip()) < 150:
            logger.info("Hindsight: Fast Path Retain (Short text)")
            record = HindsightRecord(
                text=text.strip(),
                category=MemoryCategory.EXPERIENCE,
                importance=importance or 1,
                agent_id=agent_id,
                metadata={"extraction_mode": "fast_path"},
            )
            await self.pipeline.store(
                record.text,
                metadata=record.to_qdrant_payload(),
                agent_id=agent_id,
                importance=record.importance,
            )
            return [record]

        # Tier 2: Pre-Extraction Semantic Deduplication
        # Skip LLM call if we already know this or something very similar (>0.95 similarity)
        existing = await self.pipeline.search(
            text, k=1, filter_metadata={"agent_id": agent_id} if agent_id else None
        )
        if existing and existing[0].get("distance", 1.0) < 0.05:
            logger.info("Hindsight: Skipping redundant retention (Semantic Match dist=%.4f)", existing[0]["distance"])
            return []

        # Tier 3: Deep Path (LLM Extraction)
        prompt = _RETAIN_PROMPT.format(text=text)

        try:
            logger.info("Hindsight: Deep Path Retain (LLM Extraction) len=%d", len(text))
            result = await self.llm.complete([Message(role="user", content=prompt)], tier="worker")
            raw = str(result.get("content", result) if isinstance(result, dict) else result).strip()

            logger.debug("Hindsight: Raw LLM Output: %s", raw)

            # Fail-Safe Parsing: Extract JSON block
            json_str = raw
            if "```json" in raw:
                json_str = raw.split("```json")[1].split("```")[0].strip()
            elif "```" in raw:
                json_str = raw.split("```")[1].split("```")[0].strip()

            # Find the first [ or {
            start_list = json_str.find("[")
            start_dict = json_str.find("{")

            if start_list != -1 and (start_dict == -1 or start_list < start_dict):
                # It's a list
                end = json_str.rfind("]") + 1
                json_str = json_str[start_list:end]
            elif start_dict != -1:
                # It's a single dict (wrap it in a list later)
                end = json_str.rfind("}") + 1
                json_str = json_str[start_dict:end]

            try:
                data = json.loads(json_str)
            except json.JSONDecodeError:
                # Try one repair attempt
                logger.warning("Hindsight: Initial JSON parse failed, attempting repair...")
                json_str = self._repair_json(json_str)
                data = json.loads(json_str)

            # Normalize to list
            if isinstance(data, dict):
                # Some models wrap the list in a key like "records" or "facts"
                for key in ["records", "facts", "data", "hindsight"]:
                    if key in data and isinstance(data[key], list):
                        data = data[key]
                        break
                if isinstance(data, dict):
                    data = [data]  # Single record case

            records: list[HindsightRecord] = []

            for item in data:
                if not isinstance(item, dict) or "text" not in item:
                    continue

                record = HindsightRecord(
                    text=item["text"],
                    category=MemoryCategory(item.get("category", "EXPERIENCE")),
                    importance=importance or item.get("importance", 3),
                    agent_id=agent_id,
                    metadata={"extraction_mode": "deep_path"},
                )

                # Hydrate entities
                for e in item.get("entities", []):
                    if isinstance(e, dict) and e.get("name") and str(e["name"]).lower() != "null":
                        record.entities.append(
                            Entity(name=e["name"], type=e.get("type", "GENERIC"))
                        )

                # Hydrate relations
                for r in item.get("relations", []):
                    if (
                        isinstance(r, dict)
                        and r.get("subject")
                        and r.get("object")
                        and str(r["subject"]).lower() != "null"
                        and str(r["object"]).lower() != "null"
                    ):
                        record.relations.append(
                            Relation(
                                subject=r["subject"],
                                predicate=r.get("predicate", "related_to"),
                                object=r["object"],
                            )
                        )

                # Hydrate temporal
                t_hint = item.get("temporal", {})
                if isinstance(t_hint, dict):
                    record.temporal.relative_description = t_hint.get("relative_description")

                records.append(record)

                # 3. Persistence
                # (Semantic Deduplication already performed in Tier 2 at start)

                # 3a. Vector Store
                await self.pipeline.store(
                    record.text,
                    metadata=record.to_qdrant_payload(),
                    agent_id=agent_id,
                    importance=record.importance,
                )

                # 3b. Graph Store (Neo4j)
                try:
                    for entity in record.entities:
                        await self.graph.upsert_entity(entity.name, entity.type)
                        await self.graph.link_record_to_entity(record.id, entity.name)

                    for rel in record.relations:
                        await self.graph.add_relationship(rel.subject, rel.object, rel.predicate)
                except Exception as ge:
                    logger.warning("Hindsight: Graph persistence failed: %s", ge)

            # 4. Maintenance: Occasional Memory Pruning (Garbage Collection)
            # 5% chance to trigger a prune on the current agent's collection
            if random.random() < 0.05:
                await self.prune_memories(agent_id=agent_id)

            return records

        except Exception as e:
            logger.error(f"Hindsight Retain failed: {e}")
            # Final Fallback: store raw text
            await self.pipeline.store(text, agent_id=agent_id, metadata={"error": str(e)})
            return []

    async def prune_memories(self, agent_id: str | None = None, days_old: int = 30) -> int:
        """Remove low-importance old memories from the active vector search index."""
        from qdrant_client.models import DatetimeRange, FieldCondition, Filter, Range

        # Importance <= 2 and older than days_old
        cutoff = datetime.now(UTC) - timedelta(days=days_old)

        prune_filter = Filter(
            must=[
                FieldCondition(key="importance", range=Range(lte=2.0)),
                FieldCondition(key="temporal.timestamp", range=DatetimeRange(lt=cutoff)),
            ]
        )

        try:
            if hasattr(self.pipeline, "delete_by_filter"):
                logger.info("Hindsight: Running memory pruning for agent=%s", agent_id)
                return await self.pipeline.delete_by_filter(prune_filter, agent_id=agent_id)
        except Exception as e:
            logger.error("Hindsight: Pruning failed: %s", e)
        return 0
