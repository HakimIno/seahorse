"""seahorse_ai.knowledge — Knowledge Base loader for RAG pre-population.

Load documents from multiple sources into the RAGPipeline at startup so the
agent immediately has domain knowledge without needing to call memory_store.

Supported formats
-----------------
* **JSONL** (``knowledge/*.jsonl``) — one JSON object per line:
      {"text": "...", "id": 0, "source": "optional"}
* **Markdown** (``knowledge/*.md``) — split on headings (``## ...``)
* **Plain text** (``knowledge/*.txt``) — split on blank lines (paragraphs)
* **Dict list** — pass docs directly from Python code

Usage::

    from seahorse_ai.knowledge import KnowledgeBase
    from seahorse_ai.rag import RAGPipeline

    kb = KnowledgeBase("knowledge/")
    pipeline = RAGPipeline()
    await kb.load_into(pipeline)   # embeds + indexes all docs
    # pipeline is now ready for semantic search
"""
from __future__ import annotations

import json
import logging
import os
import typing
from pathlib import Path

logger = logging.getLogger(__name__)

# Maximum characters per chunk to avoid embedding truncation
_CHUNK_MAX_CHARS = int(os.environ.get("SEAHORSE_CHUNK_MAX", "2000"))


class KnowledgeBase:
    """Loads and chunks documents from a directory or in-memory list.

    Parameters
    ----------
    source:
        Path to a directory containing ``*.md``, ``*.txt``, or ``*.jsonl``
        files.  Can also be ``None`` if you only supply docs via ``add_docs()``.

    """

    def __init__(self, source: str | Path | None = None) -> None:
        self._source = Path(source) if source else None
        self._docs: list[str] = []

    # ── add_docs ──────────────────────────────────────────────────────────────

    def add_docs(self, docs: list[str]) -> KnowledgeBase:
        """Append a list of raw text strings to the knowledge base."""
        self._docs.extend(docs)
        return self

    # ── load_into ────────────────────────────────────────────────────────────

    async def load_into(
        self,
        pipeline: object,  # RAGPipeline — avoid circular import
        *,
        verbose: bool = True,
    ) -> int:
        """Embed and index all docs into `pipeline`.

        Returns the number of documents indexed.
        """
        logger.info("KnowledgeBase: starting memory-efficient indexing …")
        indexed = 0

        # Stream documents from memory list
        for doc in self._docs:
            if not doc.strip():
                continue
            await pipeline.store(doc)  # type: ignore[attr-defined]
            indexed += 1

        # Stream documents from directory
        if self._source and self._source.is_dir():
            for doc in self._stream_dir(self._source):
                if not doc.strip():
                    continue
                await pipeline.store(doc)  # type: ignore[attr-defined]
                indexed += 1
                if verbose and indexed % 50 == 0:
                    logger.info("KnowledgeBase: indexed %d chunks …", indexed)

        logger.info("KnowledgeBase: done — %d total chunks indexed", indexed)
        return indexed

    # ── internal streaming loaders ───────────────────────────────────────────

    def _stream_dir(self, directory: Path) -> typing.Iterator[str]:
        """Yield chunks from all supported files in the directory."""
        files = sorted(directory.glob("**/*"))
        for path in files:
            if path.suffix == ".jsonl":
                yield from self._stream_jsonl(path)
            elif path.suffix == ".md":
                yield from self._stream_markdown(path)
            elif path.suffix == ".txt":
                yield from self._stream_text(path)

    def _stream_jsonl(self, path: Path) -> typing.Iterator[str]:
        """Yield chunks from a JSONL file."""
        try:
            with path.open("r", encoding="utf-8") as f:
                for line_no, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        text = obj.get("text") or obj.get("content") or str(obj)
                        if text:
                            yield from _chunk(text)
                    except json.JSONDecodeError:
                        logger.warning(
                            "KnowledgeBase: skipping bad JSON at %s:%d", path, line_no
                        )
        except OSError as exc:
            logger.error("KnowledgeBase: cannot read %s: %s", path, exc)

    def _stream_markdown(self, path: Path) -> typing.Iterator[str]:
        """Split markdown on level-2 headings (## ...) and yield chunks."""
        try:
            with path.open("r", encoding="utf-8") as f:
                current: list[str] = []
                for line in f:
                    if line.startswith("## ") and current:
                        section = "\n".join(current).strip()
                        if section:
                            yield from _chunk(section)
                        current = [line]
                    else:
                        current.append(line)
                if current:
                    section = "\n".join(current).strip()
                    if section:
                        yield from _chunk(section)
        except OSError as exc:
            logger.error("KnowledgeBase: cannot read %s: %s", path, exc)

    def _stream_text(self, path: Path) -> typing.Iterator[str]:
        """Read plain text in memory-efficient chunks and split into paragraphs."""
        try:
            with path.open("r", encoding="utf-8") as f:
                # Read file in 128KB chunks to find paragraph breaks
                buffer = ""
                chunk_size = 128 * 1024
                while True:
                    chunk_data = f.read(chunk_size)
                    if not chunk_data:
                        break
                    
                    buffer += chunk_data
                    paragraphs = buffer.split("\n\n")
                    
                    # Keep the last partial paragraph in the buffer
                    buffer = paragraphs.pop()
                    
                    for para in paragraphs:
                        if para.strip():
                            yield from _chunk(para.strip())
                
                # Yield the final paragraph
                if buffer.strip():
                    yield from _chunk(buffer.strip())
        except OSError as exc:
            logger.error("KnowledgeBase: cannot read %s: %s", path, exc)


# ── helpers ──────────────────────────────────────────────────────────────────

def _chunk(text: str, max_chars: int = _CHUNK_MAX_CHARS) -> typing.Iterator[str]:
    """Split text into chunks of at most `max_chars` characters.

    Efficiently splits on sentence boundaries, or falls back to word/char splits
    if sentences are too long.
    """
    if len(text) <= max_chars:
        yield text
        return

    # Try splitting on sentence boundaries
    sentences = text.replace("\n", " ").split(". ")
    current = []
    current_len = 0
    
    for sent in sentences:
        sent_with_sep = sent + ". "
        if current_len + len(sent_with_sep) <= max_chars:
            current.append(sent_with_sep)
            current_len += len(sent_with_sep)
        else:
            if current:
                yield "".join(current).strip()
            
            # If a single sentence is longer than max_chars, split it by characters
            if len(sent_with_sep) > max_chars:
                # Avoid infinite recursion or massive memory spikes
                inner_text = sent_with_sep
                while len(inner_text) > max_chars:
                    yield inner_text[:max_chars].strip()
                    inner_text = inner_text[max_chars:]
                current = [inner_text]
                current_len = len(inner_text)
            else:
                current = [sent_with_sep]
                current_len = len(sent_with_sep)

    if current:
        yield "".join(current).strip()
