"""WebSearch tool — searches the web using DuckDuckGo (no API key needed).

Falls back gracefully if `duckduckgo_search` is not installed.
"""
from __future__ import annotations

import logging

from seahorse_ai.tools.base import tool

logger = logging.getLogger(__name__)


def _ddg_search(query: str, max_results: int = 5) -> list[dict[str, str]]:
    try:
        from duckduckgo_search import DDGS  # type: ignore[import]
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=max_results))
    except ImportError:
        logger.warning("duckduckgo_search not installed. Run: uv add duckduckgo-search")
        return []


@tool("Search the web for up-to-date information. Returns top search results with titles and snippets.")
async def web_search(query: str, max_results: int = 5) -> str:
    """Perform a web search and return formatted results."""
    logger.info("web_search: query=%r max_results=%d", query, max_results)
    results = _ddg_search(query, max_results=max_results)

    if not results:
        return f"No results found for query: {query!r}"

    lines = [f"Search results for: {query!r}\n"]
    for i, r in enumerate(results, 1):
        title = r.get("title", "No title")
        body = r.get("body", r.get("snippet", ""))[:300]
        href = r.get("href", "")
        lines.append(f"{i}. **{title}**\n   {body}\n   URL: {href}\n")

    return "\n".join(lines)
