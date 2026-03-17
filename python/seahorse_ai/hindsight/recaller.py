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
import math
from datetime import UTC, datetime
from typing import Any

from seahorse_ai.graph_db import GraphManager
from seahorse_ai.schemas import AgentRole
from seahorse_ai.hindsight.reranker import HindsightReranker

logger = logging.getLogger(__name__)

class HindsightRecaller:
    def __init__(self, pipeline: Any) -> None:
        """Initialize with a storage pipeline."""
        self.pipeline = pipeline
        self.graph = GraphManager()
        self.reranker = HindsightReranker()

    async def recall(
        self, 
        query: str, 
        agent_id: str | None = None, 
        agent_role: AgentRole = AgentRole.WORKER,
        current_task: str = "",
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
        
        # 1. Execute Search Tasks in parallel
        results_lists = await asyncio.gather(*tasks)
        
        # 2. Fuse results using RRF and deduplicate by ID
        merged = self._rrf_fuse(results_lists, k=k*2) # Get more candidates for textual deduplication
        
        # 3. Deduplicate by Text Content (Rust-Accelerated)
        import seahorse_ffi
        merged = seahorse_ffi.deduplicate_by_text(merged)
        
        # 4. Apply Temporal Boost (Initial boost for reranker context)
        if temporal_boost:
            merged = self._apply_temporal_boost(merged)
            
        # 5. Contextual & Utility Reranking
        merged = await self.reranker.rerank(
            query=query,
            documents=merged,
            agent_role=agent_role,
            current_task=current_task,
            top_n=k
        )
        
        return merged

    async def think(self, query: str, context: list[dict[str, Any]]) -> str:
        """Priority 3: Synthesis Layer. Uses a 'thinker' model to answer the query based on retrieved context."""
        from seahorse_ai.llm import get_llm
        from seahorse_ai.schemas import Message
        
        if not context:
            return "No relevant memories found to answer this query."
            
        context_items = []
        for i, doc in enumerate(context):
            dist = doc.get("distance", 0)
            if dist == 0:
                reliability = "[Direct Fact]"
            elif dist <= 2:
                reliability = f"[Inferred - {dist} hops]"
            else:
                reliability = f"[UNCERTAIN - {dist} hops distance]"
            
            context_items.append(f"Memory {i+1} {reliability}:\n{doc.get('text', '')}")
            
        context_str = "\n\n".join(context_items)
        
        prompt = f"""You are Seahorse Hindsight, an AI with long-term evolving memory.
Answer the following query based ONLY on the retrieved memories provided below.

CRITICAL RULES:
1. If memories are marked [UNCERTAIN] or have many hops, express DOUBT (e.g. "I suspect...", "It's possible but unverified...").
2. Only state things as absolute facts if they are [Direct Fact].
3. If the memories do not contain the answer, say "I don't have enough information in my memory yet."

Query: {query}

Retrieved Memories:
{context_str}

Answer:"""
        
        try:
            client = get_llm(tier="thinker")
            resp = await client.complete([Message(role="user", content=prompt)], tier="thinker")
            return str(resp.get("content", resp)).strip()
        except Exception as e:
            logger.error(f"Reasoning synthesis failed: {e}")
            return "Internal error during reasoning synthesis."

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

    async def _graph_search(self, query: str, agent_id: str | None, k: int, hops: int = 6) -> list[dict[str, Any]]:
        """Knowledge graph traversal to find records linked to entities in the query (multi-hop)."""
        try:
            entities = await self._extract_entities_from_query(query)
            if not entities:
                entities = [w.strip("?,.!") for w in query.split() if len(w) > 3]
            
            logger.info("Recaller: Graph reasoning for entities: %s (hops=%d)", entities, hops)
            
            graph_results = []
            seen_ids = set()
            
            for entity in entities:
                # Returns list of dicts with 'id' and 'distance'
                path_hits = await self.graph.get_records_by_path(entity, hops=hops)
                
                for hit in path_hits:
                    rid = hit["id"]
                    if rid not in seen_ids:
                        # Apply score decay in the fusion layer or here
                        graph_results.append({
                            "id": rid, 
                            "graph_hit": True, 
                            "distance": hit["distance"]
                        })
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
                
                # 4. Extract/Update Vector/Cosine/Hop Score
                target = doc_map[doc_id]
                val = doc.get("vector_score") or doc.get("score") or doc.get("distance")
                
                # Context Decay Logic
                dist = doc.get("distance")
                decay = 1.0
                if dist is not None:
                    try:
                        dist = int(dist)
                        decay = 0.8 ** dist 
                        target["distance"] = dist
                    except (ValueError, TypeError):
                        pass

                if val is not None:
                    try:
                        val = float(val)
                        # If it looks like a distance (small value for match), convert to similarity
                        similarity = 1.0 - val if ("distance" in doc or val < 0.45) else val
                        
                        # Apply Decay to final vector/graph score
                        similarity *= decay
                        
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
        """Boost recent results using exponential decay.
        
        Score_final = Score_initial * e ^ (-(lambda / importance) * delta_time)
        """
        now = datetime.now(UTC)
        # lambda for decay: 0.05 gives a half-life of ~14 days for importance 1
        decay_constant = 0.05 

        for doc in results:
            meta = doc.get("metadata", doc) if isinstance(doc.get("metadata"), dict) else doc
            
            # 1. Parse Timestamp (Support both flat and nested 'temporal' field)
            ts_data = meta.get("temporal", {}) if isinstance(meta.get("temporal"), dict) else {}
            ts_str = ts_data.get("timestamp") or meta.get("timestamp")
            
            try:
                if ts_str:
                    # Handle various formats: ISO, Z, raw string
                    if isinstance(ts_str, datetime):
                        ts = ts_str
                    else:
                        ts = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
                    
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=UTC)
                else:
                    ts = now
            except (ValueError, TypeError) as e:
                logger.warning(f"Decay: Failed to parse timestamp '{ts_str}': {e}")
                ts = now

            # 2. Calculate Delta Time (in days)
            delta_days = max(0, (now - ts).total_seconds() / 86400.0)

            # 3. Get Importance (Factor 1-5)
            # Higher importance slows down the decay rate
            importance = doc.get("importance") or meta.get("importance") or 3
            try:
                importance = max(1, min(5, int(importance)))
            except (ValueError, TypeError):
                importance = 3

            # 4. Calculate Final Decay Multiplier
            # Factor 5 means it stays "fresh" 5 times longer than Factor 1
            decay_factor = math.exp(-(decay_constant / importance) * delta_days)
            
            # 5. Apply to score
            doc["temporal_decay"] = decay_factor
            
            # We use rrf_score as the base if available, otherwise vector_score
            base_score = doc.get("rrf_score", doc.get("vector_score", 0.1))
            doc["fused_score"] = base_score * decay_factor
            
            # Update the main score field for external tools
            doc["score"] = doc["fused_score"]

        # Re-sort by new fused score
        return sorted(results, key=lambda x: x.get("fused_score", 0), reverse=True)
