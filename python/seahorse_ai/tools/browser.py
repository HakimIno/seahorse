"""seahorse_ai.tools.browser — High-performance browser automation using Playwright.

Features:
- Browser singleton + Context pool for speed
- Resource blocking for faster scraping
- Support for file:// rendering (ECharts/Pyecharts)
- Concurrency control via Semaphore
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import anyio
from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)

from seahorse_ai.tools.base import tool

logger = logging.getLogger(__name__)

_PAGE_TIMEOUT   = 30_000   # ms
_NAV_TIMEOUT    = 20_000   # ms
_MAX_CONTEXTS   = 4        # concurrent pages
_VIEWPORT       = {"width": 1280, "height": 900}


# ── Browser singleton ─────────────────────────────────────────────────────────

class _BrowserPool:
    """
    Single Chromium instance, multiple isolated BrowserContexts.
    Context = incognito-like session (cookies/cache ไม่ปนกัน)
    เร็วกว่าสร้าง Browser ใหม่ทุกครั้ง ~10x
    """

    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._sem = anyio.Semaphore(_MAX_CONTEXTS)
        self._lock = asyncio.Lock()

    async def _ensure_started(self) -> Browser:
        async with self._lock:
            # Check if browser is still valid and connected
            if (
                self._browser is None 
                or not self._browser.is_connected()
                or self._playwright is None
            ):
                if self._browser:
                    try:
                        await self._browser.close()
                    except Exception:
                        pass
                if self._playwright:
                    try:
                        await self._playwright.stop()
                    except Exception:
                        pass
                
                logger.info("Starting Chromium browser singleton...")
                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                        "--no-zygote",
                        # --single-process removed for stability
                    ],
                )
            return self._browser

    @asynccontextmanager
    async def page(self) -> AsyncIterator[Page]:
        """Acquire isolated context + page, release เมื่อ done."""
        async with self._sem:
            for attempt in range(2): # Simple retry for flaky sessions
                try:
                    browser = await self._ensure_started()
                    context = await browser.new_context(
                        viewport=_VIEWPORT,
                        user_agent=(
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/120.0.0.0 Safari/537.36"
                        ),
                        java_script_enabled=True,
                        bypass_csp=True,
                        ignore_https_errors=True,
                    )
                    # Block unnecessary resources — เร็วขึ้น ~40%
                    await context.route(
                        "**/*",
                        lambda route: route.abort()
                        if route.request.resource_type in {"image", "font", "media", "stylesheet"}
                        else route.continue_(),
                    )
                    page = await context.new_page()
                    page.set_default_timeout(_PAGE_TIMEOUT)
                    page.set_default_navigation_timeout(_NAV_TIMEOUT)
                    break 
                except Exception as e:
                    if attempt == 1: raise e
                    logger.warning(f"Browser attempt {attempt} failed, retrying: {e}")
                    # Force a restart on next attempt
                    self._browser = None 
                    await asyncio.sleep(1)

            try:
                yield page
            finally:
                await context.close()  # clear cookies/cache ทันที

    async def close(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()


_pool = _BrowserPool()


# ── Tools ──────────────────────────────────────────────────────────────────────

@tool(
    "Scrape content from a webpage. Supports JavaScript-rendered pages. "
    "Returns page title, main text content, and optionally HTML.\n\n"
    "USE WHEN: target site requires JS rendering, login wall, or dynamic content.\n"
    "PREFER duckduckgo_search for simple fact-finding — faster and no browser needed."
)
async def browser_scrape(
    url: str,
    wait_for: str = "",           # CSS selector to wait for before extract
    extract_html: bool = False,
    screenshot_path: str = "",
) -> str:
    """Scrape detailed content from a website using a high-performance browser pool."""
    try:
        async with _pool.page() as page:
            response = await page.goto(url, wait_until="domcontentloaded")

            if response is None or response.status >= 400:
                return f"Error: HTTP {response.status if response else 'no response'} for {url}"

            if wait_for:
                await page.wait_for_selector(wait_for, timeout=10_000)

            title = await page.title()
            # ดึงเฉพาะ text — ตัด script/style noise ออก
            text = await page.evaluate("""() => {
                const remove = document.querySelectorAll(
                    'script, style, nav, footer, header, aside, [aria-hidden="true"]'
                );
                remove.forEach(el => el.remove());
                return document.body?.innerText?.trim() ?? '';
            }""")

            # ตัด whitespace ซ้อน
            text = " ".join(text.split())[:8000]  # cap ที่ 8k chars

            if screenshot_path:
                await page.screenshot(path=screenshot_path, full_page=True)

            result = f"URL: {url}\nTitle: {title}\n\nContent:\n{text}"

            if extract_html:
                html = await page.content()
                result += f"\n\nHTML (truncated):\n{html[:3000]}"

            return result

    except TimeoutError:
        return f"Timeout: page took >{_PAGE_TIMEOUT}ms — try a simpler selector or different URL"
    except Exception as e:
        logger.error("browser_scrape failed: %s", e)
        return f"Scrape error: {e}"


@tool(
    "Take a screenshot of a webpage or local HTML file. "
    "Useful for rendering pyecharts HTML output to PNG for reports.\n\n"
    "EXAMPLES:\n"
    "  Web page    : url='https://example.com'\n"
    "  Local chart : url='file:///home/user/chart.html'"
)
async def browser_screenshot(
    url: str,
    output_path: str = "screenshot.png",
    full_page: bool = True,
    wait_for: str = "",
) -> str:
    """Render a URL or local HTML file to a PNG image."""
    try:
        async with _pool.page() as page:
            # local file:// path รองรับ pyecharts output
            await page.goto(url, wait_until="networkidle")

            if wait_for:
                await page.wait_for_selector(wait_for, timeout=10_000)

            # รอ ECharts animation เสร็จ
            await page.wait_for_timeout(500)

            await page.screenshot(
                path=output_path,
                full_page=full_page,
                type="png",
            )
            return f"Screenshot saved → {output_path}"

    except Exception as e:
        return f"Screenshot error: {e}"


@tool(
    "Backward compatibility alias for browser_scrape. Use browser_scrape instead."
)
async def browser_scan(url: str) -> str:
    """Backward compatibility alias for browser_scrape."""
    return await browser_scrape(url)


@tool("Close the browser and release all resources. Call when agent session ends.")
async def browser_close() -> str:
    """Shutdown the background browser instance."""
    await _pool.close()
    return "Browser closed."
