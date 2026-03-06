"""seahorse_ai.tools.browser — Deep web analysis tool using Playwright.

This tool allows the agent to navigate to a URL, wait for dynamic content,
and extract the full page text for analysis.
"""
from __future__ import annotations

import logging
import re

from seahorse_ai.tools.base import tool

logger = logging.getLogger(__name__)

async def _get_browser_content(url: str) -> str:
    """Internal helper to fetch page content using Playwright."""
    from playwright.async_api import async_playwright
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            
            # Set a realistic user agent
            ua = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            await page.set_extra_http_headers({"User-Agent": ua})
            
            logger.info("browser_scan: navigating to %s", url)
            await page.goto(url, wait_until="networkidle", timeout=30000)
            
            # Simple markdown-ish extraction
            content = await page.evaluate("() => document.body.innerText")
            title = await page.title()
            
            await browser.close()
            
            # Basic cleanup: remove excessive whitespace
            content = re.sub(r'\n\s*\n', '\n\n', content)
            
            # Limit to 10k chars to avoid token issues
            return f"Source: {url}\nTitle: {title}\n\n{content[:10000]}"
            
    except Exception as exc:
        logger.error("browser_scan failed for %s: %s", url, exc)
        return f"Error scanning {url}: {exc}"

@tool(
    "Scan a website URL and extract its full text content for deep analysis. "
    "Use this when search snippets are insufficient or when you need to read a page. "
    "Input should be a valid absolute URL starting with http:// or https://."
)
async def browser_scan(url: str) -> str:
    """Navigate to a URL and return the page text content."""
    # Ensure URL is absolute
    if not url.startswith(("http://", "https://")):
        return "Error: Invalid URL. Provide an absolute URL (http:// or https://)."
        
    logger.info("browser_scan: url=%r", url)
    return await _get_browser_content(url)
