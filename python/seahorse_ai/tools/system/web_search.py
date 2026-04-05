"""WebSearch tool — Elite Edition. 

Implements a sophisticated Search-to-Context pipeline:
1. Query Expansion (Multi-query generation)
2. Breadth-First DDG Search
3. LLM-based Reranking
4. Deep Content Scraping (via Playwright)
5. Evidence Synthesis

This system is designed to be more accurate and useful than generic search APIs.
"""

from __future__ import annotations

import datetime
import logging
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Any

import anyio
import httpx

from seahorse_ai.core.llm import get_llm
from seahorse_ai.core.schemas import Message
from seahorse_ai.tools.base import tool
from seahorse_ai.tools.system.browser import browser_scrape
from seahorse_ai.tools.system.elite_search_schemas import (
    SearchReport,
    SearchSnippet,
    format_search_report,
)

logger = logging.getLogger(__name__)


def _score_domain(url: str) -> float:
    """Assign a quality score bonus/penalty based on domain."""
    trusted = [".gov", ".edu", "wikipedia.org", "reuters.com", "apnews.com", "bbc.com", "github.com", "scholar.google"]
    spam = ["pinterest.com", "quora.com", "softonic.com", "cnet.com", "ezinearticles.com"]
    
    score = 1.0
    u = url.lower()
    if any(t in u for t in trusted):
        score += 0.5
    if any(s in u for s in spam):
        score -= 0.4
    return score


async def _fast_scrape(url: str) -> str | None:
    """Attempt a fast HTTP fetch for static-heavy domains to bypass browser overhead."""
    static_domains = [
        "wikipedia.org", "github.com", "arxiv.org", "python.org", "w3schools.com",
        "reuters.com", "bbc.com", "apnews.com", "medium.com", "docs.", "blog.",
        "nasa.gov", "spacex.com", "nytimes.com",
    ]
    if not any(d in url.lower() for d in static_domains):
        return None
        
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Seahorse/1.0"}
            res = await client.get(url, headers=headers)
            if res.status_code == 200:
                # Simple text extraction for static sites (no BS4 needed for basic content)
                from html.parser import HTMLParser

                class _SimpleTextExtractor(HTMLParser):
                    def __init__(self) -> None:
                        super().__init__()
                        self.text = []
                        self.ignore = False

                    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
                        if tag in ("script", "style", "nav", "footer", "header"):
                            self.ignore = True

                    def handle_endtag(self, tag: str) -> None:
                        if tag in ("script", "style", "nav", "footer", "header"):
                            self.ignore = False

                    def handle_data(self, data: str) -> None:
                        if not self.ignore:
                            self.text.append(data)

                parser = _SimpleTextExtractor()
                parser.feed(res.text)
                content = " ".join(" ".join(parser.text).split())
                return f"URL: {url} (Static)\n\nContent:\n{content[:10000]}"
    except Exception as e:
        logger.debug("fast_scrape failed for %s: %s", url, e)
    return None


def _extract_json(content: Any) -> Any:
    """Robustly extract JSON from various LLM response formats."""
    import json
    if isinstance(content, (dict, list)):
        return content

    if not isinstance(content, str):
        return {}

    text = content.strip()
    if text.startswith("```"):
        # Handle markdown blocks
        try:
            parts = text.split("```", 2)
            if len(parts) >= 3:
                inner = parts[1]
                if inner.startswith("json"):
                    inner = inner[4:].strip()
                return json.loads(inner.strip())
        except Exception:
            pass

    # Fallback: find the first { and last } or [ and ]
    try:
        start_idx = min(
            (text.find("{") if "{" in text else float("inf")),
            (text.find("[") if "[" in text else float("inf")),
        )
        end_idx = max(text.rfind("}"), text.rfind("]"))
        if start_idx != float("inf") and end_idx != -1:
            return json.loads(text[int(start_idx) : end_idx + 1])
    except Exception:
        pass

    return {}


class _DDGLiteParser(HTMLParser):
    """Parses search results from lite.duckduckgo.com."""

    def __init__(self) -> None:
        super().__init__()
        self.results: list[SearchSnippet] = []
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
                # Basic validation
                if "title" in self._current and "href" in self._current:
                    self.results.append(
                        SearchSnippet(
                            title=self._current["title"],
                            href=self._current["href"],
                            snippet=self._current.get("snippet", ""),
                        )
                    )
                self._current = {}

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._current["title"] = self._current.get("title", "") + data.strip()
            self._current["title"] = self._current["title"].strip()
        elif self._in_snippet:
            self._current["snippet"] = self._current.get("snippet", "") + data.strip()
            self._current["snippet"] = self._current["snippet"].strip()


def _search_ddg_lite(query: str, max_results: int = 10) -> list[SearchSnippet]:
    """Fetch and parse DuckDuckGo Lite HTML."""
    try:
        # Use no time restriction (df=) for breadth or df=w for freshness
        # We default to broad search for elite mode.
        data = urllib.parse.urlencode({"q": query}).encode("utf-8")
        req = urllib.request.Request(
            "https://lite.duckduckgo.com/lite/",
            data=data,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode("utf-8")
            parser = _DDGLiteParser()
            parser.feed(html)
            return parser.results[:max_results]
    except Exception as exc:  # noqa: BLE001
        logger.error("DDGLite search failed: %s", exc)
        return []


def _expand_queries(goal: str) -> list[str]:
    """Generate search queries from the goal — zero LLM cost.
    
    Uses the original goal + a date-suffixed variant for freshness.
    The decomposer already produces focused subtask descriptions,
    so additional LLM expansion is unnecessary overhead.
    """
    queries = [goal]
    # Add a date-focused variant for time-sensitive topics
    current_year = datetime.date.today().year
    last_year = current_year - 1
    date_keywords = ["recent", "latest", str(current_year), str(last_year), "ล่าสุด", "ปี"]
    if not any(k in goal.lower() for k in date_keywords):
        queries.append(f"{goal} {last_year} {current_year}")
    return queries


def _heuristic_rerank(goal: str, snippets: list[SearchSnippet]) -> list[SearchSnippet]:
    """Zero-LLM reranking using domain trust + keyword overlap.
    
    Replaces the LLM-based reranker which was expensive (~$0.005/call)
    and frequently failed with JSON parsing errors.
    """
    if not snippets:
        return []

    goal_words = set(goal.lower().split())
    for s in snippets:
        title_words = set(s.title.lower().split())
        # Keyword overlap score (0.0 - 1.0)
        keyword_score = len(goal_words & title_words) / max(len(goal_words), 1)
        # Snippet informativeness (longer = better, capped at 0.5)
        snippet_score = min(len(s.snippet) / 200, 0.5)
        # Domain trust
        domain_score = _score_domain(s.href)
        s.score = domain_score + keyword_score + snippet_score
    
    return sorted(snippets, key=lambda x: x.score, reverse=True)[:3]


async def _analyze_content(goal: str, candidates: list[SearchSnippet]) -> SearchReport:
    """Scrape full content from candidates and synthesize a report."""
    evidence = []
    sources = []
    
    # Process top 2 candidates in parallel (reduced from 3 for speed)
    async def _scrape_one(s: SearchSnippet):
        # Try fast scrape first (HTTP, no browser overhead)
        content = await _fast_scrape(s.href)
        if not content:
            # Fallback to full browser for JS-heavy sites
            content = await browser_scrape(s.href)
            
        if content and "Error" not in content and "Timeout" not in content:
            evidence.append(content[:2000])  # Cap per source (reduced from 4000)
            sources.append(s.href)

    async with anyio.create_task_group() as tg:
        for s in candidates[:2]:  # Only top 2 candidates
            tg.start_soon(_scrape_one, s)
            
    if not evidence:
        # Fallback to snippets if scraping failed
        evidence = [f"{s.title}: {s.snippet}" for s in candidates]
        sources = [s.href for s in candidates]

    # Synthesize the findings
    llm = get_llm(tier="extract")
    prompt = [
        Message(
            role="system",
            content=(
                "You are Seahorse Research Synthesizer. Based on the provided evidence, "
                "create a structured SearchReport JSON with key_findings, evidence_snippets, "
                "sources, and uncertainties. Focus on factual data and specific numbers."
            ),
        ),
        Message(role="user", content=f"Goal: {goal}\n\nEvidence:\n" + "\n---\n".join(evidence)),
    ]
    
    try:
        res = await llm.complete(prompt, tier="extract")
        # Handle the response dictionary structure from LiteLLM
        content = res.get("content", "") if isinstance(res, dict) else getattr(res, "content", str(res))
        
        report_data = _extract_json(content)
        if not report_data or not isinstance(report_data, dict):
            raise ValueError("Synthesis failed to return valid JSON report")

        return SearchReport(
            goal=goal,
            key_findings=report_data.get("key_findings", []),
            evidence_snippets=report_data.get("evidence_snippets", []),
            sources=sources,
            uncertainties=report_data.get("uncertainties", []),
        )
    except Exception as e:
        logger.error("Synthesis failed: %s", e)
        # TOKEN OPTIMIZATION: Return much less data if synthesis fails
        return SearchReport(
            goal=goal,
            key_findings=["Research synthesis failed. Displaying limited raw data."],
            evidence_snippets=[s[:500] for s in evidence[:2]], # Only 2 small snippets
            sources=sources[:2],
            uncertainties=[f"LLM Format Error: {e}"],
        )


@tool(
    "Elite Search: Perform a deep-research web search. "
    "Uses multi-query expansion, reranking, and deep scraping to find high-quality evidence. "
    "Returns a structured Markdown report."
)
async def web_search(query: str) -> str:
    """Perform an Elite Search (Deep Research) on the web."""
    logger.info("web_search.elite: goal=%r", query)
    
    # 1. Expand queries (zero LLM cost)
    queries = _expand_queries(query)
    logger.info("web_search.elite: expanded into %d queries", len(queries))
    
    # 2. Parallel Search
    all_snippets: list[SearchSnippet] = []
    seen_hrefs = set()
    
    async def _run_search(q: str):
        results = await anyio.to_thread.run_sync(_search_ddg_lite, q, 8)
        for r in results:
            if r.href not in seen_hrefs:
                all_snippets.append(r)
                seen_hrefs.add(r.href)

    async with anyio.create_task_group() as tg:
        for q in queries:
            tg.start_soon(_run_search, q)

    if not all_snippets:
        return f"No results found for {query!r}."

    # 3. Rerank (zero LLM cost — heuristic scoring)
    top_candidates = _heuristic_rerank(query, all_snippets)
    logger.info("web_search.elite: selected %d candidates for deep analysis", len(top_candidates))
    
    # 4. Deep Analysis (Scrape + Synthesis)
    report = await _analyze_content(query, top_candidates)
    
    return format_search_report(report)
