"""RAG pipeline — embedding generation + HNSW memory search via FFI."""
from __future__ import annotations

import logging

import litellm
import numpy as np

logger = logging.getLogger(__name__)

# Graceful fallback if Rust FFI not yet built
try:
    from seahorse_ffi._core import PyAgentMemory as _PyAgentMemory  # type: ignore[import-not-found]
    _HAS_FFI = True
except ImportError:
    _HAS_FFI = False
    logger.warning("seahorse_ffi not found — using in-memory Python fallback for RAG")


class RAGPipeline:
    """Vector RAG pipeline backed by the Rust HNSW index (or Python fallback)."""

    def __init__(self, dim: int = 1536, max_docs: int = 100_000, ef: int = 100) -> None:
        self._dim = dim
        self._ef = ef
        self._texts: dict[int, str] = {}
        self._next_id = 0

        if _HAS_FFI:
            self._memory = _PyAgentMemory(dim=dim, max_elements=max_docs)
            self._use_ffi = True
        else:
            # Fallback: brute-force cosine in Python (dev only, not perf-critical)
            self._vectors: dict[int, np.ndarray] = {}
            self._use_ffi = False

    async def add(self, text: str) -> int:
        """Embed and store a document. Returns its assigned doc_id."""
        embedding = await self._embed(text)
        doc_id = self._next_id
        self._next_id += 1

        if self._use_ffi:
            self._memory.insert(doc_id, embedding.tobytes())
        else:
            self._vectors[doc_id] = embedding

        self._texts[doc_id] = text
        logger.debug("added doc_id=%d text_len=%d", doc_id, len(text))
        return doc_id

    async def search(self, query: str, k: int = 5) -> list[tuple[str, float]]:
        """Find the k most semantically similar documents."""
        embedding = await self._embed(query)

        if self._use_ffi:
            raw = self._memory.search(embedding.tobytes(), k=k)
            return [(self._texts[doc_id], dist) for doc_id, dist in raw]

        # Python fallback — cosine similarity
        if not self._vectors:
            return []
        scores: list[tuple[int, float]] = []
        for doc_id, vec in self._vectors.items():
            norm = float(np.linalg.norm(embedding) * np.linalg.norm(vec) + 1e-9)
            cos = float(np.dot(embedding, vec)) / norm
            scores.append((doc_id, 1.0 - cos))  # distance = 1 - cosine
        scores.sort(key=lambda x: x[1])
        return [(self._texts[doc_id], dist) for doc_id, dist in scores[:k]]

    async def _embed(self, text: str) -> np.ndarray:
        """Call LiteLLM embedding API and return a numpy float32 array."""
        response = await litellm.aembedding(
            model="text-embedding-3-small",
            input=text,
        )
        return np.array(response.data[0]["embedding"], dtype=np.float32)
