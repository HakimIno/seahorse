"""seahorse_ai.tools.memory — Agent memory tools backed by the Rust HNSW RAGPipeline.

These tools give the agent a persistent long-term memory:
- memory_store  → embed text and save it in the HNSW index
- memory_search → embed a query and retrieve the k most similar stored texts

A single shared RAGPipeline instance is used per process.  Call
`set_pipeline(pipeline)` before serving requests to inject a custom one
(e.g. pre-loaded with documents).
"""
from __future__ import annotations

import logging

from seahorse_ai.rag import RAGPipeline
from seahorse_ai.tools.base import tool

logger = logging.getLogger(__name__)

# Module-level singleton: shared by all agent runs in the same process
_pipeline: RAGPipeline | None = None


def get_pipeline() -> RAGPipeline:
    """Return (or lazily create) the shared RAGPipeline."""
    global _pipeline  # noqa: PLW0603
    if _pipeline is None:
        _pipeline = RAGPipeline()
        logger.info("RAGPipeline created: %r", _pipeline)
    return _pipeline


def set_pipeline(pipeline: RAGPipeline) -> None:
    """Inject a pre-configured RAGPipeline (e.g. in tests or with pre-loaded docs)."""
    global _pipeline  # noqa: PLW0603
    _pipeline = pipeline
    logger.info("RAGPipeline replaced: %r", pipeline)


@tool(
    "Store a piece of text in long-term agent memory. "
    "The text will be embedded and indexed for later retrieval. "
    "Use this to remember facts, summaries, or anything important from the conversation."
)
async def memory_store(text: str) -> str:
    """Embed and store text in the HNSW memory index."""
    pipeline = get_pipeline()
    doc_id = await pipeline.store(text)
    logger.info("memory_store: doc_id=%d text_len=%d", doc_id, len(text))
    return (
        f"Stored in memory (doc_id={doc_id}). "
        f"Memory now contains {pipeline.size} document(s)."
    )


@tool(
    "Search long-term agent memory for relevant information. "
    "Returns the top-k most semantically similar stored texts. "
    "Use this before answering questions that may have been discussed before."
)
async def memory_search(query: str, k: int = 5) -> str:
    """Search the HNSW memory index and return the top-k matching texts."""
    pipeline = get_pipeline()
    if pipeline.size == 0:
        return "Memory is empty. Nothing has been stored yet."

    results = await pipeline.search(query, k=k)
    if not results:
        return f"No relevant memories found for: {query!r}"

    lines = [f"Memory search results for: {query!r}\n"]
    for i, (text, dist) in enumerate(results, 1):
        similarity = f"{(1 - dist) * 100:.1f}%"
        lines.append(f"{i}. [{similarity} match] {text}")

    logger.info("memory_search: query_len=%d k=%d results=%d", len(query), k, len(results))
    return "\n".join(lines)
