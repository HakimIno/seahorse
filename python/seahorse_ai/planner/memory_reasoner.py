"""seahorse_ai.planner.memory_reasoner — Synthesize memories into natural answers.

Phase 4 upgrade: Instead of just dumping raw search results, the MemoryReasoner
uses an LLM to read the retrieved facts and answer the user's specific question
naturally and coherently.
"""
from __future__ import annotations

import logging

from seahorse_ai.schemas import AgentResponse, Message

logger = logging.getLogger(__name__)

_REASONER_PROMPT = """\
You are an intelligent memory assistant for the Seahorse AI agent.
The user asked a question about their stored memories.
Read the retrieved facts below and answer the user's question clearly and concisely.

Retrieved Facts:
{facts}

User's Question: "{query}"

Rules:
1. Answer ONLY based on the provided facts. Support your answer.
2. If the facts don't contain the answer, say you don't have that information in memory.
3. Be natural, polite, and direct (use Thai language).
4. Do NOT just list all facts. Synthesize them to answer the specific question.
"""

class MemoryReasoner:
    """Handles complex memory queries by searching and reasoning over facts."""

    def __init__(self, llm_backend: object, tools_registry: object) -> None:
        self._llm = llm_backend
        self._tools = tools_registry

    async def reason(self, query: str, agent_id: str) -> AgentResponse | None:
        """Search memory and synthesize an answer to the query."""
        try:
            # 1. Retrieve raw facts from vector DB
            search_result = await self._tools.call(  # type: ignore[union-attr]
                "memory_search",
                {"query": query, "k": 5, "agent_id": agent_id},
            )

            if not search_result or "No results" in str(search_result) or "empty" in str(
                search_result
            ).lower():
                logger.info("memory_reasoner: miss query=%r", query)
                return AgentResponse(
                    content="ขออภัยครับ ตอนนี้ผมยังไม่มีข้อมูลเกี่ยวกับเรื่องนี้บันทึกไว้เลยครับ 😅",
                    steps=1,
                    agent_id=agent_id,
                    elapsed_ms=0,
                )

            # 2. Synthesize answer using LLM
            prompt = _REASONER_PROMPT.format(facts=search_result, query=query)
            
            result = await self._llm.complete(  # type: ignore[union-attr]
                [Message(role="user", content=prompt)], tier="worker"
            )
            answer = str(
                result.get("content", result) if isinstance(result, dict) else result
            ).strip()

            logger.info("memory_reasoner: synthesized answer for query=%r", query)
            
            return AgentResponse(
                content=answer,
                steps=1,
                agent_id=agent_id,
                elapsed_ms=0,
            )

        except Exception as exc:
            logger.error("memory_reasoner failed: %s", exc)
            return None
