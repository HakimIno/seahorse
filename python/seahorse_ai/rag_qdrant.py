"""seahorse_ai.rag_qdrant — Persistent Vector DB using Qdrant.

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
    MatchValue,
    PointStruct,
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
        self._client = AsyncQdrantClient(url=url)
        self._initialized_collections: set[str] = set()

        logger.info(
            "QdrantRAGPipeline: url=%s collection=%s dim=%d",
            url, collection, dim,
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
        except Exception:
            pass  # Collection doesn't exist, create it

        await self._client.create_collection(
            collection_name=collection,
            vectors_config=VectorParams(
                size=self._dim,
                distance=Distance.COSINE,
            ),
        )
        self._initialized_collections.add(collection)
        logger.info("QdrantRAGPipeline: created collection=%s", collection)

    async def _embed(self, text: str) -> np.ndarray:
        """Embed text using the configured model via LiteLLM."""
        import litellm
        resp = await litellm.aembedding(
            model=self._embed_model,
            input=[text],
        )
        vec = resp.data[0]["embedding"]
        return np.array(vec, dtype=np.float32)

    # ── Public API (same as RAGPipeline) ──────────────────────────────────────

    async def store(
        self,
        text: str,
        doc_id: int | None = None,
        metadata: dict | None = None,
    ) -> int:
        """Embed text and store in Qdrant. Returns a numeric doc_id."""
        agent_id = (metadata or {}).get("agent_id")
        collection = self._collection_name(agent_id)
        await self._ensure_collection(collection)

        embedding = await self._embed(text)

        # Use UUID as Qdrant point ID (converted to int via hash for compatibility)
        point_uuid = str(uuid.uuid4())
        numeric_id = abs(hash(point_uuid)) % (2**63)

        payload: dict[str, Any] = {"text": text, **(metadata or {})}

        await self._client.upsert(
            collection_name=collection,
            points=[PointStruct(
                id=numeric_id,
                vector=embedding.tolist(),
                payload=payload,
            )],
        )
        logger.debug(
            "qdrant.store: collection=%s id=%d text_len=%d",
            collection, numeric_id, len(text),
        )
        return numeric_id

    async def search(
        self,
        query: str,
        k: int = 5,
        filter_metadata: dict | None = None,
        rerank: bool = False,  # Qdrant scores are already good — skip LLM rerank
    ) -> list[dict]:
        """Search for the k most similar stored texts."""
        k = int(k)

        # Determine collection from agent_id in filter
        agent_id = (filter_metadata or {}).get("agent_id")
        collection = self._collection_name(agent_id)

        try:
            await self._ensure_collection(collection)
        except Exception:
            return []

        embedding = await self._embed(query)

        # Build Qdrant filter from metadata (excluding agent_id which is in collection)
        qdrant_filter = None
        extra_filters = {k: v for k, v in (filter_metadata or {}).items() if k != "agent_id"}
        if extra_filters:
            conditions = [
                FieldCondition(key=key, match=MatchValue(value=value))
                for key, value in extra_filters.items()
            ]
            qdrant_filter = Filter(must=conditions)

        response = await self._client.query_points(
            collection_name=collection,
            query=embedding.tolist(),
            query_filter=qdrant_filter,
            limit=k,
            with_payload=True,
        )

        formatted: list[dict] = []
        for hit in response.points:
            payload = dict(hit.payload or {})
            text = payload.pop("text", "")
            # Qdrant cosine score is in [-1, 1] where 1 = identical
            # Convert to distance: distance = 1 - score (lower = more similar)
            distance = 1.0 - float(hit.score)
            formatted.append({
                "text": text,
                "distance": distance,
                "metadata": payload,
                "id": hit.id,
            })

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
                            must=[FieldCondition(
                                key="text", match=MatchValue(value=text)
                            )]
                        )
                    ),
                )
                logger.info("qdrant.delete: removed text=%r", text)
                return True
        return False

    async def delete_by_text_in_collection(
        self, text: str, agent_id: str | None, threshold: float = 0.1,
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
                            must=[FieldCondition(
                                key="text", match=MatchValue(value=r["text"])
                            )]
                        )
                    ),
                )
                logger.info(
                    "qdrant.delete: collection=%s removed=%r", collection, r["text"],
                )
                return True
        return False

    @property
    def size(self) -> int:
        """Returns -1 (async call needed) — use size_async instead."""
        return -1

    async def size_async(self, agent_id: str | None = None) -> int:
        """Return the number of stored vectors in the agent's collection."""
        collection = self._collection_name(agent_id)
        try:
            info = await self._client.get_collection(collection)
            return info.points_count or 0
        except Exception:
            return 0
