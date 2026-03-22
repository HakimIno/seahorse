"""seahorse_ai.tools.internal.memory_reflector — LLM-based memory consolidation.

This module provides the 'Reflector' which:
1. Scans existing memories for patterns and conflicts.
2. Generates 'Meta-Memories' or Insights that summarize multiple facts.
3. Suggests deletions of obsolete or fragmented information.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from seahorse_ai.core.llm import get_llm
from seahorse_ai.core.schemas import Message

logger = logging.getLogger(__name__)

_REFLECT_PROMPT = """\
You are a memory consolidation specialist. 
Your goal is to "Reflect" on the following list of atomic facts and generate 1-3 high-level "Insights" or "Summaries" that simplify these facts.

Facts:
{facts_text}

Rules for Insights:
- Merge related facts (e.g., if you have 3 facts about Alice's job, create 1 comprehensive fact).
- Resolve contradictions (if one says 'Price is 100' and another says 'Price is 120' with a later timestamp, keep the latest).
- Output valid JSON only:
{{
  "insights": [
    {{
      "text": "The summarized fact",
      "related_ids": [id1, id2],
      "importance": 4
    }}
  ],
  "to_delete_ids": [id_to_remove_because_obsolete]
}}

JSON Output:
"""


class MemoryReflector:
    def __init__(self, agent_id: str | None = None) -> None:
        self.agent_id = agent_id
        self.llm = get_llm("worker")

    async def reflect(self, pipeline: Any, k: int = 50) -> dict:
        """Fetch many memories, run reflection, and apply updates to pipeline."""
        # 1. Fetch recent or random memories to reflect upon
        # In a real Hindsight system, we might query Neo4j for clusters.
        # For this implementation, we search for broad terms or take recent ones.
        memories = await pipeline.search(
            "", k=k, filter_metadata={"agent_id": self.agent_id} if self.agent_id else None
        )

        if len(memories) < 3:
            return {"status": "skipped", "reason": "Not enough memories to reflect"}

        facts_text = "\n".join(
            [f"ID: {m.get('id', m.get('doc_id'))} | Fact: {m['text']}" for m in memories]
        )

        prompt = _REFLECT_PROMPT.format(facts_text=facts_text)

        try:
            result = await self.llm.complete([Message(role="user", content=prompt)], tier="worker")
            raw = str(result.get("content", result) if isinstance(result, dict) else result).strip()

            # Simple extractor for JSON from markdown blocks
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0].strip()
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0].strip()

            data = json.loads(raw)

            insights = data.get("insights", [])
            to_delete = data.get("to_delete_ids", [])

            # Apply deletions
            for pid in to_delete:
                # We need a delete_by_id in the pipeline
                if hasattr(pipeline, "delete_by_id"):
                    await pipeline.delete_by_id(pid)
                else:
                    # Fallback or log
                    logger.warning("Pipeline doesn't support delete_by_id")

            # Apply new insights
            stored_count = 0
            for insight in insights:
                await pipeline.store(
                    insight["text"],
                    metadata={
                        "agent_id": self.agent_id,
                        "fact_type": "INSIGHT",
                        "importance": insight.get("importance", 4),
                        "source": "reflection",
                    },
                )
                stored_count += 1

            return {
                "status": "success",
                "insights_created": stored_count,
                "memories_deleted": len(to_delete),
            }

        except Exception as e:
            logger.error(f"Reflection failed: {e}")
            return {"status": "error", "message": str(e)}
