"""seahorse_ai.tools.memory_extractor — LLM-based semantic fact extraction.

Replaces regex/keyword splitting with a single LLM call that:
1. Identifies ALL distinct facts in free-form text
2. Assigns each fact a semantic type (PRICE, PERSON, EVENT, etc.)
3. Extracts entity names for later filtering
4. Scores importance (1-5) for retrieval prioritization

Zero hard-coding: the LLM understands context, language, and intent.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class MemoryFact:
    """A single atomic, typed fact ready for storage."""

    text: str  # The fact as a complete sentence
    fact_type: str = "FACT"  # PRICE | PERSON | EVENT | PREFERENCE | FACT | TASK
    entities: list[str] = field(default_factory=list)  # Named entities in the fact
    knowledge_triples: list[dict[str, str]] = field(
        default_factory=list
    )  # Subject-Predicate-Object
    importance: int = 3  # 1 (low) to 5 (critical)
    language: str = "th"  # "th" or "en" — for future filtering
    temporal: str | None = None  # ISO8601 or description


_EXTRACT_PROMPT = """\
You are a precise memory extraction assistant, specializing in Hindsight-style learning.

Extract ALL distinct, atomic facts from the input text. Focus on:
1. Temporal accuracy (when things happened).
2. Entity relationships (who is connected to what).
3. Canonical facts (avoid duplicates or fluff).

Return ONLY a valid JSON array with NO markdown, NO explanation.

Each fact object:
{{
  "text": "the fact as a complete, self-contained sentence",
  "fact_type": "PRICE|PERSON|EVENT|PREFERENCE|TASK|FACT",
  "entities": ["named entities mentioned: products, people, places"],
  "knowledge_triples": [
     {{"subject": "Entity A", "predicate": "relationship", "object": "Entity B"}}
  ],
  "importance": 1-5,
  "temporal": "ISO8601 timestamp OR relative description if mentioned"
}}

Importance guide:
- 5: Critical (prices, deadlines, personal names)
- 4: Important (preferences, recurring tasks)
- 3: Useful (general info)

Rules:
- 1 fact = 1 independent piece of information.
- Always extract "Time" if mentioned (e.g. "yesterday", "at 5pm").
- Map relationships into triples for the Knowledge Graph.

Input text: "{text}"
"""


class MemoryExtractor:
    """Extract structured MemoryFacts from free-form text using an LLM."""

    def __init__(self, llm_backend: object) -> None:
        self._llm = llm_backend

    async def extract(self, text: str) -> list[MemoryFact]:
        """Extract atomic facts from text. Returns list of MemoryFact objects."""
        prompt = _EXTRACT_PROMPT.format(text=text)

        try:
            from seahorse_ai.schemas import Message

            result = await self._llm.complete(  # type: ignore[union-attr]
                [Message(role="user", content=prompt)],
                tier="worker",
            )
            raw = str(result.get("content", result) if isinstance(result, dict) else result).strip()

            # Strip markdown code fences
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0].strip()
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0].strip()

            data = json.loads(raw)
            if not isinstance(data, list):
                raise ValueError(f"Expected list, got {type(data)}")

            facts: list[MemoryFact] = []
            for item in data:
                fact_text = str(item.get("text", "")).strip()
                if not fact_text:
                    continue
                facts.append(
                    MemoryFact(
                        text=fact_text,
                        fact_type=str(item.get("fact_type", "FACT")).upper(),
                        entities=[str(e) for e in item.get("entities", [])],
                        knowledge_triples=[
                            {
                                "subject": str(t.get("subject", "")),
                                "predicate": str(t.get("predicate", "")),
                                "object": str(t.get("object", "")),
                            }
                            for t in item.get("knowledge_triples", [])
                            if isinstance(t, dict) and "subject" in t and "object" in t
                        ],
                        importance=int(item.get("importance", 3)),
                        temporal=item.get("temporal"),
                    )
                )

            if facts:
                logger.info(
                    "memory_extractor: extracted %d facts from %d chars",
                    len(facts),
                    len(text),
                )
                return facts

        except (json.JSONDecodeError, ValueError, KeyError) as exc:
            logger.warning("memory_extractor: parse error %s — using raw text", exc)
        except Exception as exc:  # noqa: BLE001
            logger.error("memory_extractor: LLM call failed: %s — using raw text", exc)

        # Fallback: treat entire input as single fact
        return [MemoryFact(text=text, fact_type="FACT", importance=3, temporal=None)]
