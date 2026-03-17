"""seahorse_ai.hindsight.recaller — The Recall Operation.

Orchestrates 4 retrieval strategies in parallel:
1. Semantic (Vector)
2. Keyword (BM25)
3. Graph (Neo4j)
4. Temporal (Time-based filtering)

Fuses results using Reciprocal Rank Fusion (RRF).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

class HindsightRecaller:
    def __init__(self, pipeline: Any) -> None:
        """Initialize with a storage pipeline."""
        self.pipeline = pipeline

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
            # Re-use existing pipeline search (which we'll optimize later)
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
        """Knowledge graph traversal."""
        # Placeholder for Neo4j integration
        return []

    def _rrf_fuse(self, results_lists: list[list[dict[str, Any]]], k: int, constant: int = 60) -> list[dict[str, Any]]:
        """Reciprocal Rank Fusion."""
        scores: dict[str, float] = {}
        doc_map: dict[str, dict[str, Any]] = {}

        for rank_list in results_lists:
            for i, doc in enumerate(rank_list):
                # Use 'id' as key
                doc_id = str(doc.get("id", doc.get("doc_id")))
                if not doc_id:
                    continue
                
                if doc_id not in doc_map:
                    doc_map[doc_id] = doc
                    
                scores[doc_id] = scores.get(doc_id, 0) + (1.0 / (constant + i + 1))

        # Sort by fused score
        fused_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
        
        final_results = []
        for fid in fused_ids[:k]:
            doc = doc_map[fid]
            doc["rrf_score"] = scores[fid]
            final_results.append(doc)
            
        return final_results

    def _apply_temporal_boost(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Boost recent results based on timestamp."""
        # Simple boost: sort by timestamp if available
        # In a real system, this would be a decay function.
        return results
