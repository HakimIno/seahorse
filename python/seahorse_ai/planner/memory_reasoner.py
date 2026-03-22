"""seahorse_ai.planner.memory_reasoner — Synthesize memories into natural answers.

Phase 4 upgrade: Instead of just dumping raw search results, the MemoryReasoner
uses an LLM to read the retrieved facts and answer the user's specific question
naturally and coherently.
"""

from __future__ import annotations

import logging

from seahorse_ai.core.schemas import AgentResponse, Message

logger = logging.getLogger(__name__)

_REASONER_PROMPT = """\
You are an intelligent memory assistant for the Seahorse AI agent.
The user asked a question about their past interactions or stored knowledge.

Today's date: {today}
Environment: Connected to a **{db_type}** corporate database.

Read the retrieved facts (memories) below and answer the user's specific question naturally and accurately.

Retrieved Facts (Vector Search):
{facts}

Graph Relationships (Entity Search):
{graph_context}

Conversation History (Immediate Context):
{history}

User's Question: "{query}"

Rules:
1. Answer the user's question DIRECTLY and CONCISELY. Prioritize the core fact.
2. INTERNAL FILTERING: Only use facts that are SIGNIFICANTLY relevant to the query.
3. ENVIRONMENT AWARENESS: Always check the 'Environment' line above. If it contains the answer (e.g. database type or system status), use it as the source of truth even if no relevant memories are found. 
4. If the question is simple, provide a 1-2 sentence response. 
5. DO NOT provide business analysis or strategic insights unless specifically requested.
6. If the information is found in Graph Relationships, present it as a clear logical connection.
7. Use a polite Thai tone. If the information isn't found in either Environment or Memories, say "I don't have that information yet" politely.
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
            # 2. Vector Search (Direct Query)
            # Remove redundant get_entities() LLM call to save 1-2 seconds.
            search_result = await self._tools.call(  # type: ignore[union-attr]
                "memory_search",
                {"query": query, "k": k, "agent_id": agent_id},
            )

            # 2a. Filter by Distance (Relevance Guard)
            # Distances > 0.5 mean the similarity is low. We filter these out.
            relevant_facts = []
            if isinstance(search_result, list):
                relevant_facts = [f for f in search_result if f.get("distance", 1.0) < 0.5]

            # Short-circuit: If we have 1 very strong match (< 0.1), skip synthesis
            if len(relevant_facts) == 1 and relevant_facts[0].get("distance", 1.0) < 0.1:
                logger.info(
                    "memory_reasoner: high-confidence match (dist < 0.1) — short-circuiting"
                )
                return AgentResponse(
                    content=relevant_facts[0]["text"],
                    steps=1,
                    agent_id=agent_id,
                    elapsed_ms=0,
                    is_direct=True,
                )

            # 2b. Graph Search (Optional/Experimental)
            # We only do this if specifically needed; for now, prioritize vector.
            graph_context = "(No structural relationships requested)"

            # 2c. Format Vector Results
            vector_facts = (
                "\n".join([f"- {f['text']}" for f in relevant_facts])
                if relevant_facts
                else "(No relevant memories found)"
            )

            # 3. Format Conversation History (Short-term)
            history_str = "(No recent history available)"
            if history:
                window = history[-10:] if len(history) > 10 else history
                history_str = "\n".join([f"- {m.role}: {m.content}" for m in window])

            # 3. Synthesize answer using LLM
            import datetime
            import os

            today = datetime.date.today().strftime("%A, %B %d, %Y")
            db_type = os.getenv("SEAHORSE_DB_TYPE", "sqlite")
            logger.info("memory_reasoner: reasoning for query=%r (detect_db=%s)", query, db_type)

            prompt = _REASONER_PROMPT.format(
                facts=vector_facts,
                graph_context=graph_context,
                history=history_str,
                query=query,
                today=today,
                db_type=db_type,
            )

            result = await self._llm.complete([Message(role="user", content=prompt)], tier="worker")
            answer = str(
                result.get("content", result) if isinstance(result, dict) else result
            ).strip()

            logger.info("memory_reasoner: synthesized answer for query=%r (db=%s)", query, db_type)

            return AgentResponse(
                content=answer,
                steps=1,
                agent_id=agent_id,
                elapsed_ms=0,
                is_direct=True,  # Signal to skip final strategist synthesis
            )

        except Exception as exc:
            logger.error("memory_reasoner failed: %s", exc)
            return None
