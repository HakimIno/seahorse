"""seahorse_ai.tools.competitor_radar — Autonomous web monitoring for competitors.

This tool combines web search and browser extraction to find and summarize
recent updates, strengths, and weaknesses of a specified competitor.
"""
from __future__ import annotations

import logging

from seahorse_ai.tools.base import tool
from seahorse_ai.tools.browser import browser_scan

logger = logging.getLogger(__name__)

async def _extract_competitor_data(llm, competitor_name: str, content: str) -> str:
    from seahorse_ai.schemas import Message
    
    prompt = (
        f"You are a market analyst. Analyze the following scraped content "
        f"about the competitor '{competitor_name}'.\n"
        "Extract exactly three things if available:\n"
        "1. Key Strengths\n"
        "2. Key Weaknesses\n"
        "3. New Features or Recent Updates\n\n"
        "Format as a concise Markdown list.\n\n"
        f"Content:\n{content[:8000]}"
    )
    
    messages = [
        Message(role="system", content="You extract concise business intelligence."),
        Message(role="user", content=prompt)
    ]
    
    try:
        res = await llm.complete(messages)
        return res
    except Exception as e:
        logger.error("Failed to extract competitor data: %s", e)
        return f"Error extracting data: {e}"

@tool(
    "Scan a competitor's website, changelog, or feature page via a URL to "
    "extract business intelligence. Use this to find their strengths, "
    "weaknesses, and new features."
)
async def competitor_radar(target_url: str, competitor_name: str) -> str:
    """Navigate to a competitor's URL and extract business intelligence."""
    logger.info("competitor_radar: scanning %r at %r", competitor_name, target_url)
    
    # Use the browser tool to deep scan the URL
    site_content = await browser_scan(target_url)
    
    if site_content.startswith("Error"):
        return f"Failed to scan competitor '{competitor_name}' at {target_url}: {site_content}"
    
    report = (
        f"### 📡 Radar Scan Results for: {competitor_name}\n"
        f"**Source:** {target_url}\n\n"
        f"**Raw Web Intelligence (Truncated):**\n{site_content[:4000]}...\n\n"
        "**Agent Instruction:** Please act as the Radar Analyst. Analyze this raw text to extract:\n"
        "1. Key Strengths\n"
        "2. Key Weaknesses\n"
        "3. New Features\n"
        "Pass this extracted intelligence to the War Room next."
    )
    
    return report
