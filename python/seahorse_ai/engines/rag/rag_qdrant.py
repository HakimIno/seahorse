"""seahorse_ai.engines.rag.rag_qdrant — Persistent Vector DB using Qdrant.

Drop-in replacement for RAGPipeline backed by Qdrant instead of in-memory HNSW.

Key benefits:
- Data persists across bot restarts
- Per-agent collection isolation (multi-user safe)
- Native payload filtering (no Python-side scanning)
- Scales to millions of documents

Usage:
    Set SEAHORSE_VECTOR_DB=qdrant in .env
    Qdrant must be running (docker run -d -p 6333:6333 qdrant/qdrant)
"""

from __future__ import annotations

import contextlib
import logging
import os
import uuid
from typing import Any

import numpy as np
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchText,
    MatchValue,
    PointStruct,
    TextIndexParams,
    TokenizerType,
    VectorParams,
)

logger = logging.getLogger(__name__)

_EMBED_MODEL = os.environ.get("SEAHORSE_EMBED_MODEL", "openrouter/baai/bge-m3")
_EMBED_DIM = 1024  # BGE-M3 output dimension


class QdrantRAGPipeline:
    """Persistent RAG pipeline using Qdrant as the vector backend.

    Implements the same interface as RAGPipeline (store/search/delete_by_text/size)
    so it can be used as a drop-in replacement.
    """

    def __init__(
        self,
        url: str = "http://localhost:6333",
        collection: str = "seahorse_memory",
        embed_model: str = _EMBED_MODEL,
        dim: int = _EMBED_DIM,
    ) -> None:
        self._url = url
        self._collection_base = collection
        self._embed_model = embed_model
        self._dim = dim
        self._client = AsyncQdrantClient(url=url, timeout=60.0)
        self._initialized_collections: set[str] = set()

        logger.info(
            "QdrantRAGPipeline: url=%s collection=%s dim=%d",
            url,
            collection,
            dim,
        )

    def _collection_name(self, agent_id: str | None) -> str:
        """Each agent gets its own collection for isolation."""
        if agent_id:
            # Sanitize agent_id for Qdrant collection name
            safe = agent_id.replace("/", "_").replace(":", "_").replace("-", "_")
            return f"{self._collection_base}_{safe}"
        return self._collection_base

    async def _ensure_collection(self, collection: str) -> None:
        """Create collection if it doesn't exist (idempotent)."""
        if collection in self._initialized_collections:
            return

        try:
            await self._client.get_collection(collection)
            self._initialized_collections.add(collection)
            return
        except Exception as e:
            if "already exists" in str(e).lower() or "409" in str(e):
                self._initialized_collections.add(collection)
                return
            pass  # Try creating it if get_collection failed for other reasons

        try:
            await self._client.create_collection(
                collection_name=collection,
                vectors_config=VectorParams(
                    size=self._dim,
                    distance=Distance.COSINE,
                ),
            )
            self._initialized_collections.add(collection)
            logger.info("QdrantRAGPipeline: created collection=%s", collection)
        except Exception as e:
            if "already exists" in str(e).lower() or "409" in str(e):
                self._initialized_collections.add(collection)
                return
            logger.error("Failed to ensure collection %s: %s", collection, e)
            raise

    async def _embed(self, text: str) -> np.ndarray:
        """Embed text using the configured model via LiteLLM with local caching."""
        # 1. Check local cache first
        if not hasattr(self, "_embed_cache"):
            self._embed_cache: dict[str, np.ndarray] = {}

        if text in self._embed_cache:
            return self._embed_cache[text]

        import litellm

        resp = await litellm.aembedding(
            model=self._embed_model,
            input=[text],
        )
        vec = resp.data[0]["embedding"]
        embedding = np.array(vec, dtype=np.float32)

        # 2. Save to cache
        self._embed_cache[text] = embedding
        return embedding

    # ── Public API (same as RAGPipeline) ──────────────────────────────────────

    async def store(
        self,
        text: str,
        doc_id: int | None = None,
        metadata: dict | None = None,
        importance: int = 3,
        agent_id: str | None = None,
    ) -> int:
        """Embed text and store in Qdrant. Returns a numeric doc_id."""
        agent_id = agent_id or (metadata or {}).get("agent_id")
        collection = self._collection_name(agent_id)
        await self._ensure_collection(collection)

        embedding = await self._embed(text)

        # Use UUID as Qdrant point ID (converted to int via hash for compatibility)
        point_uuid = str(uuid.uuid4())
        numeric_id = abs(hash(point_uuid)) % (2**63)

        payload: dict[str, Any] = {
            "text": text,
            "id": point_uuid,  # Keep the original UUID in payload for consistent retrieval
            "importance": importance,
            **(metadata or {}),
        }
        if agent_id:
            payload["agent_id"] = agent_id

        await self._client.upsert(
            collection_name=collection,
            points=[
                PointStruct(
                    id=numeric_id,
                    vector=embedding.tolist(),
                    payload=payload,
                )
            ],
        )
        logger.debug(
            "qdrant.store: collection=%s id=%d text_len=%d",
            collection,
            numeric_id,
            len(text),
        )
        return numeric_id

    async def keyword_search(
        self, query: str, agent_id: str | None, k: int
    ) -> list[dict[str, Any]]:
        """Perform only full-text keyword search."""
        collection = self._collection_name(agent_id)
        from qdrant_client.models import FieldCondition, Filter, MatchText

        results = await self._client.scroll(
            collection_name=collection,
            scroll_filter=Filter(must=[FieldCondition(key="text", match=MatchText(text=query))]),
            limit=k,
            with_payload=True,
        )

        points, _ = results
        return [
            {"id": p.id, "text": p.payload["text"], "metadata": p.payload, "distance": 0.5}
            for p in points
        ]

    async def search(
        self,
        query: str,
        k: int = 5,
        filter_metadata: dict | None = None,
        rerank: bool = False,
    ) -> list[dict]:
        """Search for the k most similar stored texts using Hybrid Search (Vector + Full-text)."""
        k = int(k)
        agent_id = (filter_metadata or {}).get("agent_id")
        collection = self._collection_name(agent_id)

        try:
            await self._ensure_collection(collection)
        except Exception:
            return []

        embedding = await self._embed(query)

        # Build Qdrant filter from metadata
        qdrant_filter = None
        extra_filters = {k: v for k, v in (filter_metadata or {}).items() if k != "agent_id"}
        if extra_filters:
            conditions = [
                FieldCondition(key=key, match=MatchValue(value=value))
                for key, value in extra_filters.items()
            ]
            qdrant_filter = Filter(must=conditions)

        # 1. Vector Search
        vector_resp = await self._client.query_points(
            collection_name=collection,
            query=embedding.tolist(),
            query_filter=qdrant_filter,
            limit=k * 2,
            with_payload=True,
        )

        # Ensure text index exists (idempotent-ish in this context)
        with contextlib.suppress(Exception):
            await self._client.create_payload_index(
                collection_name=collection,
                field_name="text",
                field_schema=TextIndexParams(
                    type="text",
                    tokenizer=TokenizerType.MULTILINGUAL,
                    lowercase=True,
                ),
            )

        keyword_filter = Filter(must=[FieldCondition(key="text", match=MatchText(text=query))])
        if qdrant_filter:
            keyword_filter.must.extend(qdrant_filter.must)

        keyword_resp = await self._client.scroll(
            collection_name=collection,
            scroll_filter=keyword_filter,
            limit=k * 2,
            with_payload=True,
        )

        # 3. Reciprocal Rank Fusion (RRF)
        # RRF Score = sum(1 / (rank + constant))
        constant = 60
        scores: dict[Any, float] = {}
        point_map: dict[Any, Any] = {}

        # Vector rankings
        for i, hit in enumerate(vector_resp.points):
            scores[hit.id] = scores.get(hit.id, 0.0) + 1.0 / (i + 1 + constant)
            point_map[hit.id] = hit

        # Keyword rankings
        for i, hit in enumerate(keyword_resp[0]):
            scores[hit.id] = scores.get(hit.id, 0.0) + 1.0 / (i + 1 + constant)
            point_map[hit.id] = hit

        # Merge and sort
        sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)

        formatted: list[dict] = []
        for pid in sorted_ids[:k]:
            hit = point_map[pid]
            payload = dict(hit.payload or {})
            text = payload.pop("text", "")

            # Use UUID from payload if available, else numeric point ID
            record_uuid = payload.get("id")
            effective_id = str(record_uuid) if record_uuid else str(hit.id)

            similarity = getattr(hit, "score", 0.5)
            try:
                similarity = float(similarity)
            except (TypeError, ValueError):
                similarity = 0.5

            # Standardize: Qdrant Cosine is similarity (1.0 = match).
            # We return distance (0.0 = match) for Hindsight.
            distance = max(0.0, min(1.0, 1.0 - similarity))

            formatted.append(
                {
                    "id": effective_id,
                    "text": text,
                    "distance": distance,
                    "metadata": payload,
                    "rrf_score": scores[pid],
                }
            )

        return formatted

    async def delete_by_text(self, text: str, threshold: float = 0.1) -> bool:
        """Find and delete the closest matching entry if within threshold."""
        # Search across all collections (we need agent context → search broadly)
        # For simplicity, search with the text itself and delete exact match
        results = await self.search(text, k=3)
        for r in results:
            if r["distance"] <= threshold and r["text"] == text:
                collection = self._collection_name(None)
                await self._client.delete(
                    collection_name=collection,
                    points_selector=FilterSelector(
                        filter=Filter(
                            must=[FieldCondition(key="text", match=MatchValue(value=text))]
                        )
                    ),
                )
                logger.info("qdrant.delete: removed text=%r", text)
                return True
        return False

    async def delete_by_text_in_collection(
        self,
        text: str,
        agent_id: str | None,
        threshold: float = 0.1,
    ) -> bool:
        """Delete text from a specific agent's collection."""
        collection = self._collection_name(agent_id)
        filter_meta = {"agent_id": agent_id} if agent_id else None
        results = await self.search(text, k=3, filter_metadata=filter_meta)

        for r in results:
            if r["distance"] <= threshold:
                await self._client.delete(
                    collection_name=collection,
                    points_selector=FilterSelector(
                        filter=Filter(
                            must=[FieldCondition(key="text", match=MatchValue(value=r["text"]))]
                        )
                    ),
                )
                logger.info(
                    "qdrant.delete: collection=%s removed=%r",
                    collection,
                    r["text"],
                )
                return True
        return False

    @property
    def size(self) -> int:
        """Returns -1 (async call needed) — use size_async instead."""
        return -1

    async def delete_by_id(self, point_id: Any) -> bool:
        """Delete a specific point from Qdrant by its ID."""
        collection = self._collection_name(None)
        try:
            await self._client.delete(
                collection_name=collection,
                points_selector=[point_id],
            )
            return True
        except Exception:
            return False

    async def delete_by_filter(self, filter_obj: Filter, agent_id: str | None = None) -> int:
        """Delete points matching a specific filter. Returns number of deleted points (if available)."""
        collection = self._collection_name(agent_id)
        try:
            result = await self._client.delete(
                collection_name=collection,
                points_selector=FilterSelector(filter=filter_obj),
            )
            logger.info("qdrant.delete_by_filter: executed on collection=%s", collection)
            return 1  # Qdrant delete returns UpdateResult, actual count not easily available in async without scroll
        except Exception as e:
            logger.error("qdrant.delete_by_filter failed: %s", e)
            return 0

    async def size_async(self, agent_id: str | None = None) -> int:
        """Return the number of stored vectors in the agent's collection."""
        collection = self._collection_name(agent_id)
        try:
            info = await self._client.get_collection(collection)
            return info.points_count or 0
        except Exception:
            return 0

    async def retrieve(self, point_id: Any, agent_id: str | None = None) -> dict | None:
        """Retrieve a specific point by ID from Qdrant."""
        collection = self._collection_name(agent_id)
        try:
            # Try numeric ID first, then search by payload id if it's a UUID string
            resp = await self._client.retrieve(
                collection_name=collection, ids=[point_id], with_payload=True
            )
            if resp:
                p = resp[0]
                payload = dict(p.payload or {})
                text = payload.pop("text", "")
                return {"id": p.id, "text": text, "metadata": payload}
            return None
        except Exception as e:
            logger.debug("qdrant.retrieve failed for id=%s: %s", point_id, e)
            return None

    async def update_metadata(
        self, point_id: Any, metadata: dict, agent_id: str | None = None
    ) -> bool:
        """Update/merge metadata for a specific point in Qdrant."""
        collection = self._collection_name(agent_id)
        try:
            await self._client.set_payload(
                collection_name=collection,
                payload=metadata,
                points=[point_id],
            )
            return True
        except Exception as e:
            logger.error("qdrant.update_metadata failed: %s", e)
            return False

    async def clear(self, agent_id: str | None = None) -> None:
        """Wipe the collection."""
        collection = self._collection_name(agent_id)
        try:
            await self._client.delete_collection(collection)
            self._initialized_collections.discard(collection)
            logger.info("Qdrant: collection %s cleared", collection)
        except Exception as e:
            logger.warning("Qdrant: clear failed: %s", e)
