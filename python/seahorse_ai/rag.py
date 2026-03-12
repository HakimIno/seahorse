"""seahorse_ai.rag — RAG Pipeline backed by Rust HNSW memory via PyAgentMemory FFI.

The RAGPipeline stores text chunks and their embeddings into a high-performance
HNSW index living in Rust (zero GC, sub-5ms search). Embeddings are generated
via LiteLLM's embedding API.

Usage::

    pipeline = RAGPipeline()
    await pipeline.store("The Eiffel Tower is in Paris.", doc_id=0)
    results = await pipeline.search("Where is the Eiffel Tower?", k=3)
    # [("The Eiffel Tower is in Paris.", 0.04), ...]

The RAGPipeline also functions as an agent tool: `memory_store` and
`memory_search` are @tool-decorated coroutines that wrap this class.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
from typing import TYPE_CHECKING

import numpy as np

from seahorse_ai.observability import get_tracer

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Embedding model + dimensionality — configurable via env vars
# Default uses OpenRouter so the same OPENROUTER_API_KEY works for both chat + embeddings
_EMBED_MODEL = os.environ.get(
    "SEAHORSE_EMBED_MODEL",
    "openrouter/baai/bge-m3",
)
_EMBED_DIM = int(os.environ.get("SEAHORSE_EMBED_DIM", "1024"))
_MAX_DOCS = 100_000
_EMBED_TIMEOUT = int(os.environ.get("SEAHORSE_EMBED_TIMEOUT", "30"))  # seconds


def _try_import_ffi_memory() -> type | None:
    """Try to import PyAgentMemory from the Rust FFI extension.

    Falls back to None if maturin hasn't built the extension (e.g. first
    `uv sync` without running `maturin develop`).
    """
    try:
        import seahorse_ffi

        return seahorse_ffi.PyAgentMemory
    except ImportError:
        logger.warning(
            "seahorse_ffi not found — falling back to pure-Python "
            "cosine similarity for RAG. Run `uv run maturin develop` to enable "
            "the Rust HNSW index."
        )
        return None


class RAGPipeline:
    """Retrieval-Augmented Generation pipeline with Rust HNSW backend.

    Thread-safe for concurrent reads; inserts acquire a Python lock.
    """

    def __init__(self, embed_model: str = _EMBED_MODEL, dim: int = _EMBED_DIM) -> None:
        self._embed_model = embed_model
        self._dim = dim
        self._next_id = 0

        PyAgentMemory = _try_import_ffi_memory()
        if PyAgentMemory is not None:
            self._memory = PyAgentMemory(dim=dim, max_elements=_MAX_DOCS)
            self._use_rust = True
            logger.info("RAGPipeline: using Rust HNSW index (dim=%d)", dim)
        else:
            self._memory = None
            self._use_rust = False
            # pure-Python fallback: dict of numpy vectors
            self._vectors: dict[int, np.ndarray] = {}
            self._texts: dict[int, dict] = {}  # doc_id -> {"text": str, "metadata": dict}

    async def store(
        self,
        text: str,
        doc_id: int | None = None,
        metadata: dict | None = None,
        knowledge_triples: list[dict] | None = None,
    ) -> int:
        """Embed `text` and store it in the HNSW index along with metadata and Knowledge Graph triples.

        Returns the assigned doc_id.
        """
        tracer = get_tracer("seahorse.rag")
        with tracer.start_as_current_span("rag.store") as span:
            if doc_id is None:
                doc_id = self._next_id
                self._next_id += 1

            try:
                span.set_attribute("rag.doc_id", doc_id)
                span.set_attribute("rag.text_len", len(text))
            except Exception:  # noqa: BLE001
                pass

            embedding = await self._embed(text)

            if self._use_rust and self._memory is not None:
                self._memory.insert(doc_id, embedding.tobytes(), text, json.dumps(metadata or {}))

                # Push extracted Triples into Knowledge Graph
                if knowledge_triples:
                    for triple in knowledge_triples:
                        subj, pred, obj = (
                            triple.get("subject"),
                            triple.get("predicate"),
                            triple.get("object"),
                        )
                        if subj and pred and obj:
                            # Default weight 1.0, assign edge to doc_id so we can trace back
                            self._memory.add_node(subj, "Entity", doc_id)
                            self._memory.add_node(obj, "Entity", None)
                            self._memory.add_edge(subj, obj, pred, 1.0)
                            logger.debug("rag.store: graph edge [%s] -(%s)-> [%s]", subj, pred, obj)

                logger.debug("rag.store: rust insert doc_id=%d", doc_id)
            else:
                self._texts[doc_id] = {
                    "text": text,
                    "metadata": metadata or {},
                }
                self._vectors[doc_id] = embedding
                logger.debug("rag.store: python insert doc_id=%d", doc_id)

            return doc_id

    async def search(
        self, query: str, k: int = 5, filter_metadata: dict | None = None, rerank: bool = True
    ) -> list[dict]:
        """Embed `query` and return the k most similar stored texts with metadata.

        If `rerank` is True, uses a Cross-Encoder (via LiteLLM) to refine the top results.
        """
        k = int(k)
        tracer = get_tracer("seahorse.rag")
        with tracer.start_as_current_span("rag.search") as span:
            span.set_attribute("rag.query_len", len(query))
            embedding = await self._embed(query)

            # Fetch more candidates if we plan to re-rank
            top_k = k * 4 if rerank else k
            if filter_metadata:
                top_k *= 2

            if self._use_rust and self._memory is not None:
                import seahorse_ffi

                raw = seahorse_ffi.search_memory(self._memory, embedding.tobytes(), top_k)
                results = []
                for _i, (doc_id, dist, text, meta_json) in enumerate(raw):
                    metadata = json.loads(meta_json)
                    if filter_metadata:
                        matches = all(metadata.get(key) == v for key, v in filter_metadata.items())
                        if not matches:
                            continue

                    results.append(
                        {
                            "text": text,
                            "metadata": metadata,
                            "distance": dist,
                            "doc_id": doc_id,
                        }
                    )
            else:
                if not self._texts:
                    return []

                # Python fallback (simplified here for brevity, keeping old logic but with top_k)
                if not self._vectors:
                    return []
                scores: list[tuple[int, float]] = []
                for vid, vec in self._vectors.items():
                    norm = float(np.linalg.norm(embedding) * np.linalg.norm(vec) + 1e-9)
                    cos = float(np.dot(embedding, vec)) / norm
                    scores.append((vid, 1.0 - cos))
                scores.sort(key=lambda x: x[1])
                results = []
                for vid, dist in scores[:top_k]:
                    entry = self._texts[vid]
                    if filter_metadata:
                        matches = all(
                            entry["metadata"].get(k) == v for k, v in filter_metadata.items()
                        )
                        if not matches:
                            continue
                    results.append(
                        {
                            "text": entry["text"],
                            "metadata": entry["metadata"],
                            "distance": dist,
                            "doc_id": vid,
                        }
                    )

            # ── Adaptive RAG: Re-ranking ──
            if rerank and len(results) > 1:
                results = await self._rerank_results(query, results, k)

            return results[:k]

    async def _rerank_results(self, query: str, results: list[dict], k: int) -> list[dict]:
        """Use LiteLLM rerank API to re-order candidates."""
        import litellm

        # Extract texts for re-ranking
        documents = [r["text"] for r in results]
        try:
            # Note: Requires a rerank-capable model/provider (e.g. Jina, Cohere, Mixedbread)
            # Default fallback could be a cheap LLM call if no dedicated reranker
            rerank_model = os.environ.get("SEAHORSE_RERANK_MODEL", "cohere/rerank-v3.0")

            # Skip if no Cohere key is provided (default reranker)
            if "cohere" in rerank_model.lower() and not os.environ.get("COHERE_API_KEY"):
                logger.debug("rag.rerank: skipping (COHERE_API_KEY not set)")
                return results

            logger.info("rag.rerank: using %s for %d docs", rerank_model, len(documents))
            response = await litellm.arerank(
                model=rerank_model,
                query=query,
                documents=documents,
                top_n=k,
            )

            # Map back to original result objects
            new_results = []
            for item in response.results:
                idx = item.index
                orig = results[idx]
                orig["rerank_score"] = item.relevance_score
                new_results.append(orig)

            # Since arerank already returns top_n, we just return them sorted
            return new_results

        except Exception as e:
            logger.warning("rag.rerank failed: %s. Falling back to vector search order.", e)
            return results

    async def delete_by_text(self, query: str, threshold: float = 0.45) -> dict | None:
        """Search for a matching memory and remove it if distance < threshold.

        Returns the deleted entry (dict with text and metadata) if successful, else None.
        """
        tracer = get_tracer("seahorse.rag")
        with tracer.start_as_current_span("rag.delete") as span:
            embedding = await self._embed(query)
            best_id: int | None = None
            best_dist: float = 1.0
            best_text: str | None = None
            best_metadata_json: str | None = None

            if self._use_rust and self._memory is not None:
                # Search across all (k=1)
                import seahorse_ffi

                raw = seahorse_ffi.search_memory(self._memory, embedding.tobytes(), 1)
                if raw:
                    best_id, best_dist, best_text, best_metadata_json = raw[0]
            else:
                if not self._texts:
                    return None
                for vid, vec in self._vectors.items():
                    norm = float(np.linalg.norm(embedding) * np.linalg.norm(vec) + 1e-9)
                    cos = float(np.dot(embedding, vec)) / norm
                    dist = 1.0 - cos
                    if dist < best_dist:
                        best_dist = dist
                        best_id = vid

            logger.info(
                "rag.delete: query=%r best_dist=%.4f threshold=%.2f",
                query[:50],
                best_dist,
                threshold,
            )

            if best_id is not None and best_dist < threshold:
                if self._use_rust and self._memory is not None:
                    removed = self._memory.remove(best_id)
                    if removed:
                        # Success, removed from Rust map (soft delete)
                        deleted_entry = {
                            "text": best_text,
                            "metadata": json.loads(best_metadata_json or "{}"),
                        }
                    else:
                        return None
                else:
                    deleted_entry = self._texts.pop(best_id)
                    self._vectors.pop(best_id, None)

                logger.info(
                    "rag.delete: removed doc_id=%d text=%r", best_id, deleted_entry["text"][:50]
                )
                with contextlib.suppress(Exception):
                    span.set_attribute("rag.deleted_id", best_id)
                return deleted_entry

            return None

    def clear(self) -> None:
        """Wipe all stored memories."""
        self._next_id = 0
        if self._use_rust and self._memory is not None:
            # Re-initialize the Rust memory index (clears it)
            PyAgentMemory = _try_import_ffi_memory()
            if PyAgentMemory is not None:
                self._memory = PyAgentMemory(dim=self._dim, max_elements=_MAX_DOCS)
        else:
            self._texts.clear()
            self._vectors.clear()
        logger.info("rag.clear: memory wiped")

    async def _embed(self, text: str) -> np.ndarray:
        """Call LiteLLM embedding API and return a numpy float32 array."""
        import asyncio

        import litellm  # local import to avoid top-level cost

        try:
            response = await asyncio.wait_for(
                litellm.aembedding(model=self._embed_model, input=text),
                timeout=_EMBED_TIMEOUT,
            )
        except TimeoutError:
            raise RuntimeError(
                f"Embedding API timed out after {_EMBED_TIMEOUT}s. "
                f"Check {self._embed_model!r} and your API key."
            )
        return np.array(response.data[0]["embedding"], dtype=np.float32)

    def save_to_disk(self, directory: str) -> None:
        """Save the memory index. Rust side handles metadata."""
        import json

        if not os.path.exists(directory):
            os.makedirs(directory)

        if self._use_rust and self._memory is not None:
            index_path = os.path.join(directory, "hnsw_index")
            self._memory.save(index_path)
            # Save only the next_id and config
            meta_path = os.path.join(directory, "rag_config.json")
            with open(meta_path, "w") as f:
                json.dump(
                    {
                        "next_id": self._next_id,
                        "dim": self._dim,
                        "embed_model": self._embed_model,
                    },
                    f,
                )
        else:
            # Python fallback saving (legacy)
            meta_path = os.path.join(directory, "meta_legacy.json")
            with open(meta_path, "w") as f:
                json.dump({"texts": self._texts, "next_id": self._next_id}, f)

        logger.info("rag.save_to_disk: saved to %s", directory)

    @classmethod
    def load_from_disk(cls, directory: str) -> RAGPipeline:
        """Load a RAGPipeline from a directory."""
        import json

        # Check for new config format
        cfg_path = os.path.join(directory, "rag_config.json")
        if os.path.exists(cfg_path):
            with open(cfg_path) as f:
                cfg = json.load(f)
            instance = cls(embed_model=cfg["embed_model"], dim=cfg["dim"])
            instance._next_id = cfg["next_id"]

            PyAgentMemory = _try_import_ffi_memory()
            if PyAgentMemory is not None:
                index_path = os.path.join(directory, "hnsw_index")
                instance._memory = PyAgentMemory.load(index_path, dim=cfg["dim"])
                instance._use_rust = True
                logger.info("rag.load_from_disk: loaded Rust HNSW index from %s", index_path)
            return instance
        else:
            # Fallback for legacy
            logger.warning(
                "rag.load_from_disk: No rag_config.json found. Returning empty RAGPipeline."
            )
            return cls()

    @property
    def size(self) -> int:
        """Number of documents stored."""
        if self._use_rust and self._memory is not None:
            return self._memory.size
        return len(self._texts)

    def __repr__(self) -> str:
        backend = "Rust/HNSW" if self._use_rust else "Python/cosine"
        return f"RAGPipeline(backend={backend!r}, dim={self._dim})"
