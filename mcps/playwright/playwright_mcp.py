"""
mcps/playwright/playwright_mcp.py

Playwright browser pool MCP — launches/manages headless chromium instances,
handles scroll actions, element clicks, and waits for selectors.
"""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import urlsplit

from playwright.async_api import async_playwright
from pydantic import BaseModel, Field

from shared.contracts.mcp_error import ErrorCode, MCPError
from shared.utils.config import Config, get_config
from shared.utils.logging import get_logger

logger = get_logger(__name__)


class BrowserInstructions(BaseModel):
    schema_version: str = Field(default="1.0", frozen=True)
    wait_for_selector: str | None = None
    scroll_to_bottom: bool = False
    click_selectors: list[str] = Field(default_factory=list)
    timeout_ms: int = 30000


class RenderResult(BaseModel):
    schema_version: str = Field(default="1.0", frozen=True)
    success: bool
    html: str | None = None
    error: MCPError | None = None


class PlaywrightMCP:
    """Headless browser context pool for JavaScript rendering."""

    def __init__(self, config: Config | None = None) -> None:
        self.config = config or get_config()
        self.semaphore = asyncio.Semaphore(self.config.concurrency.browser_instance_limit)
        self.playwright = None
        self.browser = None
        self.contexts = {}

    async def _init_browser(self) -> None:
        """Lazily initialize playwright and browser process."""
        if not self.playwright:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=self.config.browser.headless,
                args=["--disable-dev-shm-usage", "--no-sandbox"],
            )
            logger.info("Playwright browser instance launched")

    async def render(
        self,
        url: str,
        instructions: BrowserInstructions,
    ) -> RenderResult:
        """Render a URL using an active browser pool instance.

        Args:
            url: Page URL to fetch.
            instructions: Interactive actions to perform before capture.

        Returns:
            RenderResult containing HTML or MCPError envelope.
        """
        domain = urlsplit(url).netloc
        
        async with self.semaphore:
            await self._init_browser()
            
            logger.info("Acquired browser slot; opening context", url=url)
            try:
                # Maintain one context per domain to reuse sessions/cookies
                if domain not in self.contexts:
                    self.contexts[domain] = await self.browser.new_context(
                        viewport={"width": 1280, "height": 800},
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    )
                
                context = self.contexts[domain]
                page = await context.new_page()
                page.set_default_timeout(instructions.timeout_ms)

                # Navigation
                await page.goto(url, wait_until="load")

                # Handle click instructions
                for selector in instructions.click_selectors:
                    try:
                        logger.info("Executing click instruction", selector=selector)
                        await page.click(selector)
                        # Short grace period for animations/renders
                        await page.wait_for_timeout(500)
                    except Exception as e:
                        logger.warning("Click selector failed to execute", selector=selector, error=str(e))

                # Handle scrolling
                if instructions.scroll_to_bottom:
                    logger.info("Scrolling page to bottom")
                    await self._scroll_page(page)

                # Handle wait for selector
                if instructions.wait_for_selector:
                    logger.info("Waiting for visibility selector", selector=instructions.wait_for_selector)
                    await page.wait_for_selector(instructions.wait_for_selector, state="visible")

                html = await page.content()
                await page.close()

                return RenderResult(success=True, html=html)

            except Exception as e:
                logger.error("Playwright render process crashed", error=str(e), url=url)
                return RenderResult(
                    success=False,
                    error=MCPError(
                        code=ErrorCode.TIMEOUT,
                        message=f"Playwright rendering failed: {str(e)}",
                        retryable=True,
                    ),
                )

    async def _scroll_page(self, page: Any) -> None:
        """Scroll down in steps until bottom page height settles."""
        for _ in range(5):  # scroll max 5 times to avoid infinite loops on infinite scrolls
            current_height = await page.evaluate("document.body.scrollHeight")
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(1000)
            new_height = await page.evaluate("document.body.scrollHeight")
            if new_height == current_height:
                break

    async def close(self) -> None:
        """Cleanly close all open page/contexts and browser instances."""
        for context in self.contexts.values():
            await context.close()
        self.contexts.clear()

        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        logger.info("Playwright browser session pool disposed")
