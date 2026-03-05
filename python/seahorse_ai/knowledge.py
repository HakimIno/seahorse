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

    def add_docs(self, docs: list[str]) -> "KnowledgeBase":
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
        # Collect all docs
        all_docs = list(self._docs)
        if self._source and self._source.is_dir():
            all_docs.extend(self._load_dir(self._source))

        if not all_docs:
            logger.warning("KnowledgeBase.load_into: no documents found")
            return 0

        logger.info("KnowledgeBase: indexing %d chunks …", len(all_docs))
        indexed = 0
        for i, doc in enumerate(all_docs):
            if not doc.strip():
                continue
            await pipeline.store(doc)  # type: ignore[attr-defined]
            indexed += 1
            if verbose and (i + 1) % 10 == 0:
                logger.info(
                    "KnowledgeBase: indexed %d/%d …", indexed, len(all_docs)
                )

        logger.info("KnowledgeBase: done — %d chunks indexed", indexed)
        return indexed

    # ── internal loaders ─────────────────────────────────────────────────────

    def _load_dir(self, directory: Path) -> list[str]:
        docs: list[str] = []
        files = sorted(directory.glob("**/*"))
        for path in files:
            if path.suffix == ".jsonl":
                docs.extend(self._load_jsonl(path))
            elif path.suffix == ".md":
                docs.extend(self._load_markdown(path))
            elif path.suffix == ".txt":
                docs.extend(self._load_text(path))
        logger.info(
            "KnowledgeBase: loaded %d chunks from %s", len(docs), directory
        )
        return docs

    def _load_jsonl(self, path: Path) -> list[str]:
        docs: list[str] = []
        try:
            for line_no, line in enumerate(path.read_text("utf-8").splitlines(), 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    text = obj.get("text") or obj.get("content") or str(obj)
                    if text:
                        docs.extend(_chunk(text))
                except json.JSONDecodeError:
                    logger.warning(
                        "KnowledgeBase: skipping bad JSON at %s:%d", path, line_no
                    )
        except OSError as exc:
            logger.error("KnowledgeBase: cannot read %s: %s", path, exc)
        return docs

    def _load_markdown(self, path: Path) -> list[str]:
        """Split markdown on level-2 headings (## ...)."""
        docs: list[str] = []
        try:
            text = path.read_text("utf-8")
            # Split on ## headings, keeping the heading line with its content
            sections: list[str] = []
            current: list[str] = []
            for line in text.splitlines():
                if line.startswith("## ") and current:
                    sections.append("\n".join(current).strip())
                    current = [line]
                else:
                    current.append(line)
            if current:
                sections.append("\n".join(current).strip())

            for section in sections:
                if section.strip():
                    docs.extend(_chunk(section))
        except OSError as exc:
            logger.error("KnowledgeBase: cannot read %s: %s", path, exc)
        return docs

    def _load_text(self, path: Path) -> list[str]:
        """Split plain text on blank lines (paragraph-based)."""
        docs: list[str] = []
        try:
            text = path.read_text("utf-8")
            paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
            for para in paragraphs:
                docs.extend(_chunk(para))
        except OSError as exc:
            logger.error("KnowledgeBase: cannot read %s: %s", path, exc)
        return docs


# ── helpers ──────────────────────────────────────────────────────────────────

def _chunk(text: str, max_chars: int = _CHUNK_MAX_CHARS) -> list[str]:
    """Split text into chunks of at most `max_chars` characters.

    Simple sliding split on sentence boundaries ('. ').
    """
    if len(text) <= max_chars:
        return [text]

    # Try to split on sentence boundaries first
    sentences = text.replace("\n", " ").split(". ")
    chunks: list[str] = []
    current = ""
    for sent in sentences:
        candidate = (current + ". " + sent).strip() if current else sent
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                chunks.append(current.strip())
            current = sent

    if current:
        chunks.append(current.strip())

    return chunks if chunks else [text[:max_chars]]
