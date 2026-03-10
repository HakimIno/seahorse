"""seahorse_ai.planner.memory_reasoner — Synthesize memories into natural answers.

Phase 4 upgrade: Instead of just dumping raw search results, the MemoryReasoner
uses an LLM to read the retrieved facts and answer the user's specific question
naturally and coherently.
"""
from __future__ import annotations

import asyncio
import logging

from seahorse_ai.schemas import AgentResponse, Message

logger = logging.getLogger(__name__)

_REASONER_PROMPT = """\
You are an intelligent memory assistant for the Seahorse AI agent.
The user asked a question about their past interactions or stored knowledge.
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
2. INTERNAL FILTERING: Only use facts from "Retrieved Facts" or "Graph Relationships" that are SIGNIFICANTLY relevant to the query. Ignore noisy or unrelated facts.
3. If the question is simple, provide a 1-2 sentence response. 
4. DO NOT provide business analysis or strategic insights unless specifically requested.
5. If the information is found in Graph Relationships, present it as a clear logical connection.
6. Use a polite Thai tone. If the information isn't found, say "I don't have that information yet" politely.
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

            # 2. Parallel Retrieval (Performance Optimization)
            # Use LLM-based Entity Extraction instead of Regex for maximum accuracy
            # and parallelize the Vector + Graph searching.

            async def get_entities():
                extract_prompt = (
                    "Extract unique ENTITIES (Names, Companies, Products) from the query below. "
                    "Return only a comma-separated list of entities in Thai or English. "
                    "If none found, return 'NONE'.\n\n"
                    f"Query: {query}"
                )
                res = await self._llm.complete([Message(role="user", content=extract_prompt)], tier="worker")
                raw = str(res.get("content", res) if isinstance(res, dict) else res).strip()
                if "NONE" in raw.upper(): return set()
                return {e.strip() for e in raw.split(",") if len(e.strip()) > 1}

            # 2a. Run Vector Search + Entity Extraction in parallel
            vector_task = self._tools.call("memory_search", {"query": query, "k": k, "agent_id": agent_id})
            entities_task = get_entities()
            
            search_result, unique_entities = await asyncio.gather(vector_task, entities_task)

            # 2b. Format Vector Results
            vector_facts = "\n".join([f"- {f['text']}" for f in search_result]) if search_result else "(No relevant long-term memories found)"

            # 2c. Run Graph Neighbor searches in parallel for all extracted entities
            graph_tasks = [self._tools.call("graph_search_neighbors", {"entity": entity}) for entity in unique_entities]
            graph_results = await asyncio.gather(*graph_tasks) if graph_tasks else []
            
            graph_lines = [res for res in graph_results if "Graph relationships" in res]
            graph_context = "\n".join(graph_lines) if graph_lines else "(No structural relationships found)"

            # 3. Format Conversation History (Short-term)
            history_str = "(No recent history available)"
            if history:
                window = history[-10:] if len(history) > 10 else history
                history_str = "\n".join([f"- {m.role}: {m.content}" for m in window])

            # 3. Synthesize answer using LLM
            # [OPTIMIZATION] We remove the separate 'Reranker' LLM call to reduce latency.
            # Instead, we pass ALL facts to the Synthesis prompt and let it filter internally.
            prompt = _REASONER_PROMPT.format(
                facts=vector_facts, 
                graph_context=graph_context,
                history=history_str, 
                query=query
            )
            
            result = await self._llm.complete(
                [Message(role="user", content=prompt)], tier="worker"
            )
            answer = str(result.get("content", result) if isinstance(result, dict) else result).strip()

            logger.info("memory_reasoner: synthesized answer for query=%r", query)
            
            return AgentResponse(
                content=answer,
                steps=1,
                agent_id=agent_id,
                elapsed_ms=0,
                is_direct=True, # Signal to skip final strategist synthesis
            )

        except Exception as exc:
            logger.error("memory_reasoner failed: %s", exc)
            return None
