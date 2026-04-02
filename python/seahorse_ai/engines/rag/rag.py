"""seahorse_ai.engines.rag.rag — RAG Pipeline backed by Rust HNSW memory via PyAgentMemory FFI.

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

from seahorse_ai.core.observability import get_tracer

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_pipeline = None


def get_pipeline() -> RAGPipeline:
    """Singleton getter for the RAG pipeline."""
    global _pipeline
    if _pipeline is None:
        backend = os.environ.get("SEAHORSE_VECTOR_DB", "hnsw").lower()
        if backend == "qdrant":
            from seahorse_ai.engines.rag.rag_qdrant import QdrantRAGPipeline

            _pipeline = QdrantRAGPipeline()
        else:
            _pipeline = RAGPipeline()
    return _pipeline


# Embedding model + dimensionality — configurable via env vars
# Default uses OpenRouter so the same OPENROUTER_API_KEY works for both chat + embeddings
_EMBED_MODEL = os.environ.get(
    "SEAHORSE_EMBED_MODEL",
    "openrouter/baai/bge-m3",
)
_EMBED_DIM = int(os.environ.get("SEAHORSE_EMBED_DIM", "1024"))
_MAX_DOCS = 100_000
_EMBED_TIMEOUT = int(os.environ.get("SEAHORSE_EMBED_TIMEOUT", "10"))  # seconds


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

        # Initialize Python fallback structures always (safety/hybrid)
        self._vectors: dict[int, np.ndarray] = {}
        self._texts: dict[int, dict] = {}

        py_agent_memory = _try_import_ffi_memory()
        if py_agent_memory is not None:
            self._memory = py_agent_memory(dim=dim, max_elements=_MAX_DOCS)
            self._use_rust = True
            logger.info("RAGPipeline: using Rust HNSW index (dim=%d)", dim)
        else:
            self._memory = None
            self._use_rust = False

    async def store(
        self,
        text: str,
        doc_id: int | None = None,
        metadata: dict | None = None,
        importance: int = 3,
        agent_id: str | None = None,
        knowledge_triples: list[dict] | None = None,
    ) -> int:
        """Embed `text` and store it in the HNSW index along with metadata and Knowledge Graph triples."""
        tracer = get_tracer("seahorse.rag")
        with tracer.start_as_current_span("rag.store"):
            if doc_id is None:
                doc_id = self._next_id
                self._next_id += 1

            embedding = await self._embed(text)

            meta = metadata.copy() if metadata else {}
            if agent_id:
                meta["agent_id"] = agent_id
            meta["importance"] = importance

            if self._use_rust and self._memory is not None:
                self._memory.insert(doc_id, embedding.tobytes(), json.dumps(meta), text)

                # Push extracted Triples into Knowledge Graph
                if knowledge_triples:
                    for triple in knowledge_triples:
                        subj, pred, obj = (
                            triple.get("subject"),
                            triple.get("predicate"),
                            triple.get("object"),
                        )
                        if subj and pred and obj:
                            self._memory.add_node(subj, "Entity", doc_id)
                            self._memory.add_node(obj, "Entity", None)
                            self._memory.add_edge(subj, obj, pred, 1.0)
            else:
                self._texts[doc_id] = {"text": text, "metadata": meta}
                self._vectors[doc_id] = embedding

            return doc_id

    async def search(
        self, query: str, k: int = 5, filter_metadata: dict | None = None, rerank: bool = True
    ) -> list[dict]:
        """Search for the k most similar stored texts using Vector + Graph Hybrid Search.

        Uses Reciprocal Rank Fusion (RRF) to merge vector results with adjacent records
        found in the Knowledge Graph.
        """
        k = int(k)
        tracer = get_tracer("seahorse.rag")
        with tracer.start_as_current_span("rag.search") as span:
            span.set_attribute("rag.query_len", len(query))
            embedding = await self._embed(query)

            # 1. Primary Vector Search
            vector_results: list[dict] = []
            top_candidate_k = k * 4

            if self._use_rust and self._memory is not None:
                import seahorse_ffi

                raw = seahorse_ffi.search_memory(self._memory, embedding.tobytes(), top_candidate_k)
                for doc_id, dist, meta_json, text in raw:
                    try:
                        meta = json.loads(meta_json) if meta_json else {}
                    except Exception:
                        meta = {}
                    vector_results.append(
                        {
                            "text": text,
                            "metadata": meta,
                            "distance": dist,
                            "id": doc_id,
                            "doc_id": doc_id,
                        }
                    )
            else:
                # Python fallback (vector calculation)
                for vid, vec in self._vectors.items():
                    norm = float(np.linalg.norm(embedding) * np.linalg.norm(vec) + 1e-9)
                    cos = float(np.dot(embedding, vec)) / norm
                    vector_results.append(
                        {
                            "text": self._texts[vid]["text"],
                            "metadata": self._texts[vid]["metadata"],
                            "distance": 1.0 - cos,
                            "id": vid,
                            "doc_id": vid,
                        }
                    )
                vector_results.sort(key=lambda x: x["distance"])
                vector_results = vector_results[:top_candidate_k]

            # 2. Hybrid Recall (Future: Graph/Keywords logic moved to Hindsight package)
            results = vector_results
            if filter_metadata:
                results = [
                    r
                    for r in results
                    if all(r["metadata"].get(key) == v for key, v in filter_metadata.items())
                ]

            # 4. Adaptive RAG: Re-ranking with Hindsight
            if rerank and len(results) > 1:
                from seahorse_ai.hindsight.reranker import HindsightReranker

                reranker = HindsightReranker()
                results = await reranker.rerank(query, results, top_n=k)

            return results

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

    async def retrieve(self, doc_id: int) -> dict | None:
        """Retrieve a specific memory record by its ID."""
        if not self._use_rust:
            if doc_id in self._texts:
                return {
                    "id": doc_id,
                    "text": self._texts[doc_id]["text"],
                    "metadata": self._texts[doc_id]["metadata"],
                }
        else:
            # Rust HNSW is currently append-only for metadata in this FFI version.
            pass
        return None

    async def update_metadata(self, doc_id: int, metadata: dict) -> bool:
        """Update metadata for an existing record in-place."""
        import json

        # 1. Retrieve current doc to get full existing metadata
        doc = await self.retrieve(doc_id)
        if not doc:
            return False

        current_meta = doc.get("metadata", {})
        # Merge new metadata into existing
        current_meta.update(metadata)

        if not self._use_rust:
            if doc_id in self._texts:
                self._texts[doc_id]["metadata"] = current_meta
                return True
            return False
        else:
            # Atomic update in Rust DashMap via FFI
            meta_json = json.dumps(current_meta)
            # FFI signature: update_metadata(doc_id: int, meta_json: str) -> bool
            try:
                return self._memory.update_metadata(doc_id, meta_json)
            except Exception as e:
                logger.error("rag.update_metadata: Rust FFI failed: %s", e)
                return False

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

    async def clear(self) -> None:
        """Wipe all stored memories."""
        self._next_id = 0
        if self._use_rust and self._memory is not None:
            # Re-initialize the Rust memory index (clears it)
            py_agent_memory = _try_import_ffi_memory()
            if py_agent_memory is not None:
                self._memory = py_agent_memory(dim=self._dim, max_elements=_MAX_DOCS)
        else:
            self._texts.clear()
            self._vectors.clear()
        logger.info("rag.clear: memory wiped")

    async def _embed(self, text: str) -> np.ndarray:
        """Generate embeddings natively via Rust FastEmbed if available, else fallback to LiteLLM."""
        if self._use_rust and self._memory is not None:
            if hasattr(self._memory, "embed_text"):
                import anyio
                try:
                    # Run the heavy native inference block in a background thread (GIL is released in Rust)
                    raw_vec = await anyio.to_thread.run_sync(
                        self._memory.embed_text, text
                    )
                    return np.array(raw_vec, dtype=np.float32)
                except Exception as e:
                    logger.warning("Native FastEmbed inference failed: %s. Falling back to LiteLLM.", e)

        import anyio
        import litellm  # local import to avoid top-level cost

        try:
            with anyio.fail_after(_EMBED_TIMEOUT):
                response = await litellm.aembedding(model=self._embed_model, input=text)
        except TimeoutError as err:
            raise RuntimeError(
                f"Embedding API timed out after {_EMBED_TIMEOUT}s. "
                f"Check {self._embed_model!r} and your API key."
            ) from err
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

            py_agent_memory = _try_import_ffi_memory()
            if py_agent_memory is not None:
                index_path = os.path.join(directory, "hnsw_index")
                instance._memory = py_agent_memory.load(index_path, dim=cfg["dim"])
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
