#!/usr/bin/env python3
"""seahorse-load-kb — Pre-load a knowledge base directory into Seahorse RAG memory.

Usage::

    # Pre-load knowledge/ directory
    uv run python -m seahorse_ai.load_kb knowledge/

    # Pre-load with a custom embedding model
    SEAHORSE_EMBED_MODEL=openrouter/openai/text-embedding-3-small \\
      uv run python -m seahorse_ai.load_kb knowledge/

    # Pre-load and save to a vector snapshot (future feature)
    uv run python -m seahorse_ai.load_kb knowledge/ --save snapshot.bin

After indexing, the docs are stored in the RAGPipeline singleton via memory_store.
This script is intended as a pre-flight step before starting the server, or as a
standalone batch job for offline document ingestion.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)


async def main(source: Path) -> int:
    from seahorse_ai.knowledge import KnowledgeBase
    from seahorse_ai.rag import RAGPipeline

    logger.info("Loading knowledge base from: %s", source)

    pipeline = RAGPipeline()
    logger.info("RAGPipeline backend: %r", pipeline)

    kb = KnowledgeBase(source)
    count = await kb.load_into(pipeline, verbose=True)

    if count == 0:
        logger.warning("No documents were indexed.")
        return 1

    logger.info("✅ Indexed %d chunks. Running a quick test search …", count)

    # Quick smoke-test
    results = await pipeline.search("What is Seahorse?", k=2)
    if results:
        logger.info("Test search results:")
        for res in results:
            text = res["text"] if isinstance(res, dict) else res[0]
            dist = res["distance"] if isinstance(res, dict) else res[1]
            logger.info("  [%.1f%% match] %s …", (1 - dist) * 100, text[:80])
    else:
        logger.warning("No results returned from test search.")

    logger.info("Done. Total documents in memory: %d", pipeline.size)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pre-load knowledge base into Seahorse RAG")
    parser.add_argument("source", type=Path, help="Path to knowledge base directory")
    args = parser.parse_args()

    if not args.source.is_dir():
        print(f"Error: {args.source} is not a directory", file=sys.stderr)
        sys.exit(1)

    sys.exit(asyncio.run(main(args.source)))
