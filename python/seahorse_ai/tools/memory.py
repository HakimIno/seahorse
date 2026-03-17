"""seahorse_ai.tools.memory — Agent memory tools backed by the vector store.

Supports two backends (set via env var SEAHORSE_VECTOR_DB):
  - "qdrant" → QdrantRAGPipeline (persistent, recommended for production)
  - "hnsw"   → RAGPipeline with Rust HNSW (in-memory, default/fallback)

Tools:
  - memory_store  → embed text and save it in the vector index
  - memory_search → embed a query and retrieve the k most similar stored texts
  - memory_delete → remove a specific memory entry
"""

from __future__ import annotations

import json
import logging
import os

from seahorse_ai.tools.base import tool

logger = logging.getLogger(__name__)

# Module-level singleton: shared by all agent runs in the same process
_pipeline = None


def get_pipeline() -> object:
    """Return (or lazily create) the shared vector pipeline.

    Auto-selects backend from SEAHORSE_VECTOR_DB env var:
    - "qdrant" → QdrantRAGPipeline (persistent)
    - anything else → in-memory Rust HNSW (default)
    """
    global _pipeline  # noqa: PLW0603
    if _pipeline is None:
        backend = os.environ.get("SEAHORSE_VECTOR_DB", "hnsw").lower()
        if backend == "qdrant":
            try:
                from seahorse_ai.rag_qdrant import QdrantRAGPipeline

                url = os.environ.get("QDRANT_URL", "http://localhost:6333")
                collection = os.environ.get("QDRANT_COLLECTION", "seahorse_memory")
                _pipeline = QdrantRAGPipeline(url=url, collection=collection)
                logger.info("memory: using Qdrant backend url=%s", url)
            except Exception as exc:
                logger.error("memory: Qdrant unavailable (%s) — falling back to HNSW", exc)
                from seahorse_ai.rag import RAGPipeline

                _pipeline = RAGPipeline()
        else:
            from seahorse_ai.rag import RAGPipeline

            _pipeline = RAGPipeline()
            logger.info("memory: using in-memory HNSW backend")
    return _pipeline


def set_pipeline(pipeline: object) -> None:
    """Inject a pre-configured pipeline (e.g. in tests or with pre-loaded docs)."""
    global _pipeline  # noqa: PLW0603
    _pipeline = pipeline
    logger.info("memory: pipeline replaced with %r", pipeline)


@tool(
    "Save a specific piece of information into long-term memory for future use. "
    "CRITICAL: Store ONLY ONE independent fact at a time. "
    "If you have multiple facts (e.g. name AND preference), call this tool multiple times. "
    "DO NOT combine unrelated facts into one string."
)
async def memory_store(text: str, importance: int = 3, agent_id: str | None = None) -> str:
    """Save text into memory. Automatically splits grouped facts and injects metadata."""
    pipeline = get_pipeline()
    import datetime

    timestamp = datetime.datetime.now().isoformat()
    metadata = {
        "created_at": timestamp,
        "importance": importance,
        "agent_id": agent_id,
    }

    logger.debug("memory_store: request=%r metadata=%r", text, metadata)

    # Force splitting by common conjunctions or newlines to ensure atomic facts
    split_markers = [" และ ", " and ", "\n", " ทั้งยัง ", " รวมถึง "]
    needs_split = any(m in text for m in split_markers) and len(text) > 25

    if needs_split:
        temp_text = text
        for m in split_markers:
            temp_text = temp_text.replace(m, "SPLIT_TOKEN")

        parts = [p.strip() for p in temp_text.split("SPLIT_TOKEN") if len(p.strip()) > 3]

        if len(parts) > 1:
            stored = []
            for p in parts:
                p = p.strip(". ")
                doc_id = await pipeline.store(p, metadata=metadata)
                stored.append(p)
                logger.info("memory_store: split_stored doc_id=%d text=%r", doc_id, p)
            return f"Stored {len(stored)} atomic facts: {', '.join(stored)}"

    # 1. Search for existing similar facts to prevent duplicates or resolve conflicts
    results = await pipeline.search(
        text, k=1, filter_metadata={"agent_id": agent_id} if agent_id else None
    )

    if results:
        best = results[0]
        best_text = best["text"]
        best_dist = best["distance"]

        # Duplicate Check: If distance is < 0.08, it's effectively the same fact.
        if best_dist < 0.08:
            logger.info("memory_store: skipping duplicate (dist=%.4f) text=%r", best_dist, text)
            return f"Memory already contains this information: {best_text!r}"

        # Conflict/Update Check: distance < 0.12 = same topic, updated value.
        # NOTE: 0.25 was too aggressive — "Packet A ราคา 1200" and
        # "Packet B ราคา 5000" had dist ~0.2 (both contain "ราคา")
        # but are DIFFERENT products. Keep threshold tight.
        if best_dist < 0.12:
            await pipeline.delete_by_text(best_text, threshold=0.1)
            doc_id = await pipeline.store(text, metadata=metadata)
            logger.info("memory_store: conflict resolved. Updated %r -> %r", best_text, text)
            return f"Updated existing memory: {best_text!r} is now {text!r}"

    # 2. Decision: Direct Sync or Transactional Outbox?
    backend = os.environ.get("SEAHORSE_VECTOR_DB", "hnsw").lower()
    if backend == "qdrant":
        # Phase 2: Transactional Outbox Pattern
        import asyncpg

        pg_uri = os.environ.get("SEAHORSE_PG_URI")
        if pg_uri:
            try:
                conn = await asyncpg.connect(pg_uri)
                try:
                    await conn.execute(
                        """
                        INSERT INTO seahorse_outbox (event_type, payload)
                        VALUES ($1, $2)
                    """,
                        "MEMORY_STORE",
                        json.dumps({"text": text, "metadata": metadata}),
                    )
                    logger.info("memory_store: queued to outbox text_len=%d", len(text))
                    return f"บันทึกข้อมูลเข้าคิวเรียบร้อยครับ (Transactional Outbox) ✅: {text[:50]}..."
                finally:
                    await conn.close()
            except Exception as e:
                logger.error("memory_store outbox error: %s — falling back to direct sync", e)

    # 3. Default: Store as a new fact (Direct Sync / Fallback)
    from seahorse_ai.llm import get_llm
    from seahorse_ai.tools.memory_extractor import MemoryExtractor

    # Extract distinct facts and relationships before saving
    extractor = MemoryExtractor(get_llm("worker"))
    facts = await extractor.extract(text)

    stored_ids = []
    for fact in facts:
        # Merge semantic fact type into metadata
        fact_meta = dict(metadata)
        fact_meta["fact_type"] = fact.fact_type

        doc_id = await pipeline.store(
            fact.text, metadata=fact_meta, knowledge_triples=fact.knowledge_triples
        )
        stored_ids.append(str(doc_id))
        logger.info(
            "memory_store: stored doc_id=%d text=%r triples=%d",
            doc_id,
            fact.text[:50],
            len(fact.knowledge_triples),
        )

    return (
        f"Stored {len(stored_ids)} semantic facts in long-term memory (IDs={','.join(stored_ids)}). "
        f"Memory now contains {pipeline.size} document(s)."
    )


@tool(
    "Search long-term agent memory for relevant information. "
    "Returns the top-k most semantically similar stored texts. "
    "Use this before answering questions that may have been discussed before."
)
async def memory_search(
    query: str, k: int = 10, agent_id: str | None = None, min_similarity: float = 0.1, top_k: int | None = None
) -> list[dict] | str:
    """Search memory index. Returns dicts for planner or string for LLM."""
    if top_k is not None:
        k = top_k
    k = int(k)
    pipeline = get_pipeline()
    if pipeline.size == 0:
        return "Memory is empty."

    filter_metadata = {"agent_id": agent_id} if agent_id else None
    results = await pipeline.search(query, k=k, filter_metadata=filter_metadata)

    if not results:
        return []

    # 1. Filter by minimum similarity (distance = 1 - similarity)
    # Threshold for noise reduction (default 0.1 similarity = 0.9 distance)
    results = [r for r in results if r["distance"] < (1.0 - min_similarity)]

    if not results:
        return []

    # 2. Prioritize by importance + similarity
    results.sort(
        key=lambda x: (x["metadata"].get("importance", 3), 1 - x["distance"]), reverse=True
    )

    # 3. Decision: Return raw for planner OR string for LLM
    # If called via ReAct loop (agent_id in context), usually wants the string.
    # If called via MemoryReasoner (internal), usually wants the list.
    return results


@tool(
    "Delete a specific piece of information from long-term memory. "
    "Provide a query that describes what you want to forget. "
    "The tool will find the closest match and remove it if it is a strong match."
)
async def memory_delete(query: str) -> str:
    """Search for and delete a matching memory entry."""
    backend = os.environ.get("SEAHORSE_VECTOR_DB", "hnsw").lower()
    if backend == "qdrant":
        import asyncpg

        pg_uri = os.environ.get("SEAHORSE_PG_URI")
        if pg_uri:
            try:
                conn = await asyncpg.connect(pg_uri)
                try:
                    await conn.execute(
                        """
                        INSERT INTO seahorse_outbox (event_type, payload)
                        VALUES ($1, $2)
                    """,
                        "MEMORY_DELETE",
                        json.dumps({"query": query}),
                    )
                    logger.info("memory_delete: queued to outbox query=%r", query)
                    return f"ส่งคำขอลบข้อมูลเข้าคิวเรียบร้อยครับ (Transactional Outbox) 🗑️: {query}"
                finally:
                    await conn.close()
            except Exception as e:
                logger.error("memory_delete outbox error: %s — falling back to direct sync", e)

    pipeline = get_pipeline()
    logger.debug("memory_delete: query=%r", query)
    deleted_entry = await pipeline.delete_by_text(query)

    if deleted_entry:
        logger.info("memory_delete: DELETED %r", deleted_entry["text"])
        return f"Successfully deleted from memory: {deleted_entry['text']!r}"

    return f"No strong match found in memory to delete for query: {query!r}"


@tool(
    "Wipe ALL long-term agent memories. This action is IRREVERSIBLE. "
    "Only use this if the user explicitly asks to clear all memory, reset, or wipe everything."
)
async def memory_clear() -> str:
    """Wipe the entire memory index."""
    pipeline = get_pipeline()
    pipeline.clear()
    return "All long-term memories have been permanently deleted."
