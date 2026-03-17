"""seahorse_ai.hindsight.recaller — The Recall Operation.

Orchestrates 4 retrieval strategies in parallel:
1. Semantic (Vector)
2. Keyword (BM25)
3. Graph (Neo4j)
4. Temporal (Time-based filtering)

Fuses results using Reciprocal Rank Fusion (RRF).
"""

import asyncio
import logging
from typing import Any

import re
from seahorse_ai.graph_db import GraphManager

logger = logging.getLogger(__name__)

class HindsightRecaller:
    def __init__(self, pipeline: Any) -> None:
        """Initialize with a storage pipeline."""
        self.pipeline = pipeline
        self.graph = GraphManager()

    async def recall(
        self, 
        query: str, 
        agent_id: str | None = None, 
        k: int = 10,
        temporal_boost: bool = True
    ) -> list[dict[str, Any]]:
        """Perform parallel recall and fusion."""
        
        # Define search tasks
        tasks = [
            self._vector_search(query, agent_id, k),
            self._keyword_search(query, agent_id, k),
            self._graph_search(query, agent_id, k),
        ]
        
        # Execute in parallel
        results_lists = await asyncio.gather(*tasks)
        
        # Flat list for fusion
        merged = self._rrf_fuse(results_lists, k=k)
        
        # Apply Temporal Boost if needed
        if temporal_boost:
            merged = self._apply_temporal_boost(merged)
            
        return merged

    async def _vector_search(self, query: str, agent_id: str | None, k: int) -> list[dict[str, Any]]:
        """Standard semantic search."""
        try:
            results = await self.pipeline.search(query, k=k, filter_metadata={"agent_id": agent_id} if agent_id else None)
            return results or []
        except Exception as e:
            logger.error(f"Vector search failed: {e}")
            return []

    async def _keyword_search(self, query: str, agent_id: str | None, k: int) -> list[dict[str, Any]]:
        """Exact match search."""
        if hasattr(self.pipeline, "keyword_search"):
            return await self.pipeline.keyword_search(query, agent_id, k)
        return []

    async def _graph_search(self, query: str, agent_id: str | None, k: int) -> list[dict[str, Any]]:
        """Knowledge graph traversal to find records linked to entities in the query (multi-hop)."""
        try:
            # 1. Precise Entity Extraction using LLM
            # (In production, use a fast/cheap model)
            entities = await self._extract_entities_from_query(query)
            if not entities:
                # Fallback to broad word extraction if LLM fails or is empty
                entities = [w.strip("?,.!") for w in query.split() if len(w) > 3]
            
            logger.info("Recaller: Graph reasoning for entities: %s", entities)
            
            graph_results = []
            seen_ids = set()
            
            for entity in entities:
                # 2. Multi-hop traversal: Find records connected within 2 hops of the query entity
                record_ids = await self.graph.get_records_by_path(entity, hops=2)
                
                for rid in record_ids:
                    if rid not in seen_ids:
                        graph_results.append({"id": rid, "graph_hit": True})
                        seen_ids.add(rid)
                        
            return graph_results
        except Exception as e:
            logger.error("Hindsight Recaller: Graph search failed: %s", e)
            return []

    async def _extract_entities_from_query(self, query: str) -> list[str]:
        """Use a lightweight LLM call to extract canonical entities from the query."""
        from seahorse_ai.llm import get_llm
        from seahorse_ai.schemas import Message

        prompt = f"""Extract proper nouns (Names, Projects, Organizations) from this query. 
Return ONLY a comma-separated list of entities. Example: James Chen, Project Orion.
Query: {query}
Entities:"""
        
        try:
            client = get_llm(tier="extract")
            resp = await client.complete([Message(role="user", content=prompt)], tier="extract")
            content = resp.get("content", "").strip()
            
            if not content or "none" in content.lower():
                return []
            
            entities = [e.strip() for e in content.split(",") if len(e.strip()) > 1]
            return entities
        except Exception as e:
            logger.warning("Recaller: LLM Entity Extraction failed: %s", e)
            return []

    def _rrf_fuse(self, results_lists: list[list[dict[str, Any]]], k: int, constant: int = 60) -> list[dict[str, Any]]:
        """Reciprocal Rank Fusion."""
        scores: dict[str, float] = {}
        doc_map: dict[str, dict[str, Any]] = {}

        for rank_list in results_lists:
            for i, doc in enumerate(rank_list):
                # 1. Normalize ID: Prioritize the Record UUID over numeric point IDs
                # In Qdrant, the persistent ID is usually in doc.id or doc.payload['id']
                meta = doc.get("metadata", {}) or {}
                
                # Candidates for ID:
                # - meta.id (UUID)
                # - doc.id (Might be UUID or numeric 0)
                # - doc.doc_id
                # - if doc is a payload dict, 'id' might be the UUID
                
                candidates = [
                    meta.get("id"),
                    doc.get("id"),
                    doc.get("doc_id"),
                    doc.get("metadata", {}).get("id") if isinstance(doc.get("metadata"), dict) else None
                ]
                
                # Find the first string that looks like a UUID (length > 10)
                doc_id = None
                for c in candidates:
                    if isinstance(c, str) and len(c) > 10:
                        doc_id = c
                        break
                
                # Fallback to whatever is available
                if not doc_id:
                    for c in candidates:
                        if c is not None:
                            doc_id = str(c)
                            break
                            
                if not doc_id:
                    continue
                
                # 2. Accumulate RRF Score
                scores[doc_id] = scores.get(doc_id, 0) + (1.0 / (constant + i + 1))

                # 3. Merge Document Data: Favor rich records over shells
                if doc_id not in doc_map or (len(str(doc.get("text", ""))) > len(str(doc_map[doc_id].get("text", "")))):
                    # Keep track of flags from the old version if it existed
                    prev_graph_hit = doc_map[doc_id].get("graph_hit", False) if doc_id in doc_map else False
                    prev_v_score = doc_map[doc_id].get("vector_score") if doc_id in doc_map else None
                    
                    # Store a copy to avoid reference issues
                    doc_map[doc_id] = doc.copy()
                    
                    # FORCE IDEAL ID: Standardize result object to use the UUID as its primary ID
                    doc_map[doc_id]["id"] = doc_id
                    
                    if prev_graph_hit:
                        doc_map[doc_id]["graph_hit"] = True
                    if prev_v_score is not None and doc_map[doc_id].get("vector_score") is None:
                        doc_map[doc_id]["vector_score"] = prev_v_score
                
                # Update flags from the current doc being processed
                if doc.get("graph_hit"):
                    doc_map[doc_id]["graph_hit"] = True
                
                # 4. Extract/Update Vector/Cosine Score
                target = doc_map[doc_id]
                # Try to get similarity from various possible fields
                val = doc.get("vector_score") or doc.get("score") or doc.get("distance")
                if val is not None:
                    try:
                        val = float(val)
                        # If it looks like a distance (small value for match), convert to similarity
                        # In Qdrant, similarity is usually 0.5-1.0, distance is 0.0-0.5
                        similarity = 1.0 - val if ("distance" in doc or val < 0.45) else val
                        
                        # Only update if we don't have a score or this one is better
                        if target.get("vector_score") is None or similarity > target["vector_score"]:
                            target["vector_score"] = similarity
                    except (ValueError, TypeError):
                        pass

        # Sort by fused score
        fused_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
        
        final_results = []
        for fid in fused_ids[:k]:
            if fid in doc_map:
                doc = doc_map[fid]
                doc["rrf_score"] = scores[fid]
                final_results.append(doc)
            
        return final_results

    def _apply_temporal_boost(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Boost recent results."""
        # Simple sorting by timestamp if present in metadata
        return sorted(
            results, 
            key=lambda x: str(x.get("metadata", {}).get("timestamp", "")), 
            reverse=True
        )
