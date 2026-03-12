"""WebSearch tool — searches the web using DuckDuckGo Lite (no API key needed).

Uses a custom HTML scraper for `lite.duckduckgo.com` which is extremely
resilient to bot-blocking and requires zero external dependencies.
"""

from __future__ import annotations

import logging
import urllib.parse
import urllib.request
from html.parser import HTMLParser

from seahorse_ai.tools.base import tool

logger = logging.getLogger(__name__)


class _DDGLiteParser(HTMLParser):
    """Parses search results from lite.duckduckgo.com."""

    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._current: dict[str, str] = {}
        self._in_title = False
        self._in_snippet = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag == "a" and "result-link" in attrs_dict.get("class", ""):
            self._current = {"href": attrs_dict.get("href", "")}
            self._in_title = True
        elif tag == "td" and "result-snippet" in attrs_dict.get("class", ""):
            self._in_snippet = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_title:
            self._in_title = False
        elif tag == "td" and self._in_snippet:
            self._in_snippet = False
            if self._current:
                self.results.append(self._current)
                self._current = {}

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._current["title"] = self._current.get("title", "") + data.strip()
            self._current["title"] = self._current["title"].strip()
        elif self._in_snippet:
            self._current["snippet"] = self._current.get("snippet", "") + data.strip()
            self._current["snippet"] = self._current["snippet"].strip()


def _search_ddg_lite(query: str, max_results: int = 5) -> list[dict[str, str]]:
    """Fetch and parse DuckDuckGo Lite HTML."""
    try:
        # df=w restricts results to the past week, preventing old news from appearing
        data = urllib.parse.urlencode({"q": query, "df": "w"}).encode("utf-8")
        req = urllib.request.Request(
            "https://lite.duckduckgo.com/lite/",
            data=data,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode("utf-8")
            parser = _DDGLiteParser()
            parser.feed(html)
            # Ensure max_results is an integer to avoid slice index errors
            max_results_int = int(max_results)
            return parser.results[:max_results_int]
    except Exception as exc:  # noqa: BLE001
        logger.error("DDGLite search failed: %s", exc)
        return []


@tool("Search the web for up-to-date information. Returns top search results.")
async def web_search(query: str, max_results: int = 5) -> str:
    """Perform a web search and return formatted results."""
    # Cast early to prevent logging and indexing errors
    max_results = int(max_results)
    logger.info("web_search: query=%r max_results=%d", query, max_results)

    # Run synchronous network call in executor to avoid blocking async loop
    import asyncio

    loop = asyncio.get_running_loop()
    results = await loop.run_in_executor(None, _search_ddg_lite, query, max_results)

    if not results:
        return (
            f"No results found for query: {query!r}. "
            "[SYSTEM: Do not hallucinate. Explain to the user "
            "that no current news/data was found instead of guessing.]"
        )

    lines = [f"Search results for: {query!r}\n"]
    for i, r in enumerate(results, 1):
        title = r.get("title", "No title")
        body = r.get("snippet", "")[:300]
        href = r.get("href", "")
        lines.append(f"{i}. **{title}**\n   {body}\n   URL: {href}\n")

    results_str = "\n".join(lines)
    results_str += (
        "\n\n[SYSTEM: If the headlines and snippets above give you enough information "
        "to answer the user's question, YOU MUST STOP and ANSWER now. "
        "Do NOT call browser_scan to waste time/money if the summary is sufficient.]"
    )
    return results_str
