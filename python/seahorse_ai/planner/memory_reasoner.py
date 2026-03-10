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
The user asked a question about their past interactions or stored knowledge.
Read the retrieved facts (memories) below and answer the user's specific question naturally and accurately.

Retrieved Facts (Memories):
{facts}

Conversation History (Immediate Context):
{history}

User's Question: "{query}"

Rules:
1. Answer based on BOTH the provided facts and the immediate conversation history. 
2. If the user asks about something that just happened, look at the "Conversation History".
3. If the facts or history contain past questions or answers, summarize them to prove you remember.
4. If the information isn't in either, clearly state what you know and what you don't.
5. Use a natural, polite, and helpful Thai executive tone.
6. Do NOT just list all facts. Synthesize them into a coherent narrative that directly addresses the user's intent.
"""

class MemoryReasoner:
    """Handles complex memory queries by searching and reasoning over facts."""

    def __init__(self, llm_backend: object, tools_registry: object) -> None:
        self._llm = llm_backend
        self._tools = tools_registry

    async def reason(
        self,
        query: str,
        agent_id: str,
        history: list[Message] | None = None,
        k: int = 3,
    ) -> AgentResponse | None:
        """Search memory AND history, then synthesize a natural response."""
        try:
            # 1. Retrieve raw facts from vector DB (Long-term)
            # Use the tool call for vector search
            search_result = await self._tools.call(  # type: ignore[union-attr]
                "memory_search",
                {"query": query, "k": k, "agent_id": agent_id},
            )

            # 2. Format facts
            facts_str = "\n".join([f"- {f['text']}" for f in search_result]) if search_result else "(No relevant long-term memories found)"

            # 3. Format Conversation History (Short-term)
            history_str = "(No recent history available)"
            if history:
                # Optimization: Synthesis only needs the last 10 messages for context
                window = history[-10:] if len(history) > 10 else history
                history_str = "\n".join([f"- {m.role}: {m.content}" for m in window])

            # 3. Synthesize answer using LLM
            prompt = _REASONER_PROMPT.format(
                facts=facts_str, 
                history=history_str, 
                query=query
            )
            
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
