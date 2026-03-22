from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from seahorse_ai.core.schemas import AgentResponse, Message
from seahorse_ai.planner.fast_utils import split_entities
from seahorse_ai.planner.handlers.base import BaseFastHandler

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class EntityHandler(BaseFastHandler):
    """Handles direct entity extraction and project structure analysis."""

    async def handle(
        self, prompt: str, history: list[Message] | None, start_t: float, **kwargs: Any
    ) -> AgentResponse | None:
        intent = kwargs.get("intent", "direct")
        if intent == "internal":
            return await self._handle_internal_analysis(prompt, start_t)
        return await self._handle_direct_extraction(prompt, history, start_t)

    async def _handle_direct_extraction(
        self, prompt: str, history: list[Message] | None, start_t: float
    ) -> AgentResponse | None:
        try:
            extraction_prompt = f"Identify all specific entities (Names, Organizations, Locations) from this request. Return ONLY comma-separated list of entities. Request: {prompt}"
            res = await self._llm.complete(
                [Message(role="user", content=extraction_prompt)], tier="fast"
            )
            raw_entities = str(res.get("content", res) if isinstance(res, dict) else res)
            entities = split_entities(raw_entities)

            kb_tasks = [self._tools.call("search_kb", {"query": e}) for e in entities]
            kb_results = await asyncio.gather(*kb_tasks)

            summary = "\n\n".join(kb_results)
            synthesis_prompt = (
                f"Summarize these findings based on: {prompt}\n\nFindings:\n{summary}"
            )
            final_res = await self._llm.complete(
                [Message(role="user", content=synthesis_prompt)], tier="worker"
            )
            content = str(
                final_res.get("content", final_res) if isinstance(final_res, dict) else final_res
            )

            return AgentResponse(
                content=content,
                steps=len(entities) + 1,
                elapsed_ms=int((time.perf_counter() - start_t) * 1000),
            )
        except Exception as e:
            logger.error(f"EntityHandler direct: {e}")
            return None

    async def _handle_internal_analysis(self, prompt: str, start_t: float) -> AgentResponse | None:
        try:
            # Simple repo structure analysis
            structure = await self._tools.call("list_dir", {"DirectoryPath": "."})
            analysis_prompt = f"Analyze project structure for: {prompt}\n\nStructure:\n{structure}"
            res = await self._llm.complete(
                [Message(role="user", content=analysis_prompt)], tier="worker"
            )
            content = str(res.get("content", res) if isinstance(res, dict) else res)
            return AgentResponse(
                content=content, steps=3, elapsed_ms=int((time.perf_counter() - start_t) * 1000)
            )
        except Exception as e:
            logger.error(f"EntityHandler internal: {e}")
            return None
