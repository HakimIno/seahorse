"""seahorse_ai.planner.memory_recorder — Rate-limited background memory summarization.

Extracts key facts from conversations and stores them in the HNSW memory index.
Includes rate limiting and deduplication to prevent API cost spikes.
"""
from __future__ import annotations

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
        "Analyze the conversation below and extract KEY FACTS, USER PREFERENCES, "
        "and IMPORTANT CONTEXT that should be remembered for future interactions. "
        "CRITICAL: Each fact MUST be independent. "
        "For each fact, assign an 'importance' level from 1 to 5: "
        "5 = Critical/Permanent (e.g. name, birthday), "
        "3 = Standard preference (e.g. food, hobbies), "
        "1 = Contextual/Temporary (e.g. today's plan). "
        "Format: [importance] Fact text. "
        "Example:\n- [5] The user's name is Kim.\n- [3] The user likes Thai Tea.\n"
        "If no new facts are found, return 'NONE'.\n\n"
        "### Conversation History ###\n"
    )

    SPLIT_MARKERS: tuple[str, ...] = (" และ ", " and ", "\n", " ทั้งยัง ", " รวมถึง ")

    def __init__(self, llm: object, tools: object) -> None:
        self._llm = llm
        self._tools = tools
        self._last_run: float = 0.0

    async def record(self, messages: list[Message], agent_id: str | None = None) -> None:
        """Analyze conversation and store key facts. Rate-limited and non-blocking."""
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

            for line in raw.split("\n"):
                line = line.strip("-* ").strip()
                if not line or len(line) < 5:
                    continue
                importance, fact = self._parse_fact_line(line)
                await self._store_fact(fact, importance, agent_id)

            logger.info("memory_recorder: processed facts for agent_id=%s", agent_id)

        except Exception as exc:  # noqa: BLE001
            logger.error("memory_recorder: failed: %s", exc)

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
            for part in parts:
                await self._tools.call(  # type: ignore[union-attr]
                    "memory_store",
                    {"text": part, "importance": importance, "agent_id": agent_id},
                )
        else:
            await self._tools.call(  # type: ignore[union-attr]
                "memory_store",
                {"text": text, "importance": importance, "agent_id": agent_id},
            )
