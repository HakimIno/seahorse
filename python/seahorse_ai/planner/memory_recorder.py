"""seahorse_ai.planner.memory_recorder — Rate-limited background memory summarization.

Extracts key facts from conversations and stores them in the HNSW memory index.
Includes rate limiting and deduplication to prevent API cost spikes.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from seahorse_ai.schemas import Message

logger = logging.getLogger(__name__)


class MemoryRecorder:
    """Extract and store conversation facts asynchronously.

    Rate limiting:
    - Will not summarize more than once every MIN_INTERVAL_SECONDS.
    - Requires at least MIN_MESSAGES to contain enough signal.

    Deduplication:
    - Each extracted fact is split atomically before storing.
    - The underlying RAGPipeline handles semantic duplicate detection.
    """

    MIN_MESSAGES: int = 3
    MIN_INTERVAL_SECONDS: float = 5.0

    SUMMARY_SYSTEM_PROMPT = (
        "You are a background memory worker. "
        "Analyze the conversation below and extract KEY FACTS and RELATIONSHIPS. "
        "1. ENTITY RELATIONSHIPS: Extract triples in the format [REL] (Subject) --[RELATION]--> (Object). "
        "   Example: [REL] (Somchai) --[WORKS_AT]--> (Apple). "
        "2. ATOMIC FACTS: Extract user preferences or general knowledge. "
        "   Assign importance (1-5). Format: [importance] Fact text. "
        "   Example: [5] The user's name is Kim. "
        "If no new information is found, return 'NONE'.\n\n"
        "### Conversation History ###\n"
    )

    SPLIT_MARKERS: tuple[str, ...] = (" และ ", " and ", "\n", " ทั้งยัง ", " รวมถึง ")

    def __init__(self, llm: object, tools: object) -> None:
        self._llm = llm
        self._tools = tools
        self._last_run: float = 0.0
        self._is_syncing: bool = False

    async def record(self, messages: list[Message], agent_id: str | None = None) -> None:
        """Analyze conversation and store key facts. Rate-limited and non-blocking."""
        # ... (previous implementation)
        # ── 1. Start outbox processing if not already running ──────────────────
        if not self._is_syncing:
            asyncio.create_task(self.process_outbox())
            self._is_syncing = True

        # Rate limit check
        now = time.monotonic()
        if now - self._last_run < self.MIN_INTERVAL_SECONDS:
            logger.debug("memory_recorder: rate limited, skipping")
            return

        # Minimum message threshold
        non_system = [m for m in messages if m.role != "system"]
        if len(non_system) < self.MIN_MESSAGES:
            return

        self._last_run = now

        history_text = "\n".join(
            f"{m.role}: {m.content}" for m in non_system
        )
        try:
            from seahorse_ai.schemas import Message as Msg
            response = await self._llm.complete([  # type: ignore[union-attr]
                Msg(role="system", content=self.SUMMARY_SYSTEM_PROMPT + history_text)
            ])
            raw = str(response.get("content", "") if isinstance(response, dict) else response)

            if "NONE" in raw.upper() or len(raw.strip()) < 5:
                return

            storage_tasks = []
            for line in raw.split("\n"):
                line = line.strip("-* ").strip()
                if not line or len(line) < 5:
                    continue
                
                if line.startswith("[REL]"):
                    import re
                    match = re.search(r"\((.+)\)\s*--\[(.+)\]-->\s*\((.+)\)", line)
                    if match:
                        storage_tasks.append(self._tools.call(
                            "graph_store_triple", 
                            {"subject": match.group(1), "predicate": match.group(2), "object_entity": match.group(3)}
                        ))
                else:
                    importance, fact = self._parse_fact_line(line)
                    storage_tasks.append(self._store_fact(fact, importance, agent_id))

            if storage_tasks:
                await asyncio.gather(*storage_tasks)

            logger.info("memory_recorder: processed %d facts for agent_id=%s", len(storage_tasks), agent_id)

        except Exception as exc:  # noqa: BLE001
            logger.error("memory_recorder: failed: %s", exc)

    async def process_outbox(self) -> None:
        """Background loop to sync seahorse_outbox with Qdrant."""
        import json
        import os

        import asyncpg

        from seahorse_ai.tools.memory import get_pipeline

        pg_uri = os.environ.get("SEAHORSE_PG_URI")
        if not pg_uri:
            return

        logger.info("memory_recorder: starting Transactional Outbox worker")
        while True:
            try:
                conn = await asyncpg.connect(pg_uri)
                try:
                    # Get pending events
                    rows = await conn.fetch("""
                        SELECT id, event_type, payload 
                        FROM seahorse_outbox 
                        WHERE status = 'PENDING' 
                        LIMIT 10
                        FOR UPDATE SKIP LOCKED
                    """)
                    
                    if not rows:
                        await asyncio.sleep(5)
                        continue

                    pipeline = get_pipeline()
                    for row in rows:
                        event_id = row['id']
                        event_type = row['event_type']
                        payload = json.loads(row['payload'])
                        
                        try:
                            if event_type == "MEMORY_STORE":
                                await pipeline.store(
                                    payload['text'], 
                                    metadata=payload.get('metadata')
                                )
                            elif event_type == "MEMORY_DELETE":
                                await pipeline.delete_by_text(payload['query'])
                            
                            await conn.execute("""
                                UPDATE seahorse_outbox 
                                SET status = 'SYNCED', synced_at = NOW() 
                                WHERE id = $1
                            """, event_id)
                            logger.info("outbox worker: synced event_id=%d type=%s", event_id, event_type)
                        except Exception as e:
                            logger.error("outbox worker: failed event_id=%d: %s", event_id, e)
                            await conn.execute("""
                                UPDATE seahorse_outbox 
                                SET status = 'FAILED', error_message = $1 
                                WHERE id = $2
                            """, str(e), event_id)

                finally:
                    await conn.close()

            except Exception as e:
                logger.error("outbox worker: connection error: %s", e)
                await asyncio.sleep(10)

    # ── Private helpers ────────────────────────────────────────────────────────

    def _parse_fact_line(self, line: str) -> tuple[int, str]:
        """Parse '[N] Fact text' into (importance, fact_text)."""
        importance = 3
        if line.startswith("[") and "]" in line[:5]:
            try:
                imp_str = line[1:line.index("]")]
                importance = int(imp_str)
                line = line[line.index("]") + 1:].strip()
            except (ValueError, IndexError):
                pass
        return importance, line

    async def _store_fact(
        self, text: str, importance: int, agent_id: str | None
    ) -> None:
        """Store a single atomic fact, splitting on conjunctions if needed."""
        needs_split = any(m in text for m in self.SPLIT_MARKERS) and len(text) > 25

        if needs_split:
            temp = text
            for marker in self.SPLIT_MARKERS:
                temp = temp.replace(marker, "SPLIT_TOKEN")
            parts = [p.strip() for p in temp.split("SPLIT_TOKEN") if len(p.strip()) > 3]
            
            tasks = [
                self._tools.call(
                    "memory_store",
                    {"text": part, "importance": importance, "agent_id": agent_id},
                ) for part in parts
            ]
            await asyncio.gather(*tasks)
        else:
            await self._tools.call(  # type: ignore[union-attr]
                "memory_store",
                {"text": text, "importance": importance, "agent_id": agent_id},
            )
