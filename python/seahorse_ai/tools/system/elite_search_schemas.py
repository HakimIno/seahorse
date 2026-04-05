from __future__ import annotations

import msgspec


class SearchSnippet(msgspec.Struct):
    """A raw snippet from a search engine."""

    title: str
    href: str
    snippet: str
    source: str = "duckduckgo"
    score: float = 0.0  # Relevance score (0.0 - 1.0)


class ExpandedQueries(msgspec.Struct):
    """A list of search queries generated from a user prompt."""

    queries: list[str]
    reasoning: str


class SearchReport(msgspec.Struct):
    """A synthesized report from deep search findings."""

    goal: str
    key_findings: list[str]
    evidence_snippets: list[str]
    sources: list[str]
    uncertainties: list[str]


def format_search_report(report: SearchReport) -> str:
    """Format a SearchReport as a structured markdown string for the LLM."""
    lines = [f"# Search Findings: {report.goal}\n"]
    
    if report.key_findings:
        lines.append("## Key Findings")
        for f in report.key_findings:
            lines.append(f"- {f}")
        lines.append("")

    if report.evidence_snippets:
        lines.append("## Evidence & Data")
        for s in report.evidence_snippets:
            lines.append(f"> {s}")
        lines.append("")

    if report.sources:
        lines.append("## Sources")
        for src in report.sources:
            lines.append(f"- {src}")
        lines.append("")

    if report.uncertainties:
        lines.append("## Uncertainties & Missing Data")
        for u in report.uncertainties:
            lines.append(f"⚠️ {u}")

    return "\n".join(lines)
