"""
mcps/execution/execution_mcp.py

Execution MCP — the SOLE gateway for fetching internet resources.
Applies HTTP with anti-bot challenge checks and escalates to Playwright
browser rendering when JS challenges/dynamic elements are detected.
"""

from __future__ import annotations

import time
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

from mcps.execution.cache import Cache
from mcps.execution.http_client import HTTPClient
from mcps.execution.rate_limiter import RateLimiter
from mcps.playwright.playwright_mcp import BrowserInstructions, PlaywrightMCP
from shared.contracts.mcp_error import ErrorCode, MCPError
from shared.models.website_profile import WebsiteProfile
from shared.utils.config import Config, get_config
from shared.utils.logging import get_logger

logger = get_logger(__name__)


class FetchResult(BaseModel):
    schema_version: str = Field(default="1.0", frozen=True)
    success: bool
    html: str | None = None
    status_code: int | None = None
    fetch_method: Literal["requests", "playwright"]
    latency_ms: float
    from_cache: bool
    is_csr: bool = False
    error: MCPError | None = None


class ExecutionMCP:
    """Gatekeeper for fetches enforcing caching, rate limits, and fallback escalation."""

    def __init__(self, config: Config | None = None) -> None:
        self.config = config or get_config()
        self.http_client = HTTPClient(self.config)
        self.rate_limiter = RateLimiter(self.config)
        self.cache = Cache(self.config)
        self.playwright = PlaywrightMCP(self.config)

    async def smart_fetch(
        self,
        url: str,
        context: WebsiteProfile,
    ) -> FetchResult:
        """Executes smart_fetch decision tree.

        Steps:
        1. Cache Check.
        2. Check if preferred_fetch_method == 'playwright'.
        3. Acquire domain semaphore + delay jitter.
        4. Attempt standard HTTP request. Check anti-bot challenges (403, low size, challenge keywords).
        5. Escalate to Playwright browser context if challenges triggered.
        """
        domain = urlsplit(url).netloc
        start_time = time.perf_counter()

        # Step 1: Cache Check
        cached_html = await self.cache.get(url)
        if cached_html:
            logger.info("Cache hit", url=url)
            res = FetchResult(
                success=True,
                html=cached_html,
                status_code=200,
                fetch_method="requests",
                latency_ms=(time.perf_counter() - start_time) * 1000.0,
                from_cache=True,
            )
            self._log_execution_diagnostics(url, res)
            return res

        # Step 2: Escalate immediately if profile recommends playwright
        if context.preferred_fetch_method == "playwright":
            logger.info("Escalating to Playwright immediately per profile recommendation", url=url)
            res = await self._fetch_via_playwright(url, start_time)
            self._log_execution_diagnostics(url, res)
            return res

        # Step 3: Rate Limiting & Semaphore Slot Acquisition
        await self.rate_limiter.acquire(domain)
        await self.rate_limiter.wait_with_jitter(domain)

        try:
            # Step 4: HTTP Request with backoff retries
            status_code = None
            body = None
            headers = None
            retry_count = 0
            max_retries = self.config.retries.max_attempts

            while retry_count < max_retries:
                try:
                    status_code, body, headers = await self.http_client.get(
                        url, timeout_ms=self.config.browser.timeout_ms
                    )
                    
                    if status_code == 200:
                        # Check anti-bot indicators or CSR templates
                        is_csr = self._is_js_template(body)
                        if self._is_bot_challenge(body) or is_csr:
                            logger.warning("Bot challenge or JS template detected; escalating to Playwright", url=url, is_csr=is_csr)
                            self.rate_limiter.release(domain)
                            context.preferred_fetch_method = "playwright"
                            res = await self._fetch_via_playwright(url, start_time)
                            res.is_csr = is_csr
                            self._log_execution_diagnostics(url, res)
                            return res
                        
                        # Cache & return
                        await self.cache.set(url, body)
                        self.rate_limiter.release(domain)
                        res = FetchResult(
                            success=True,
                            html=body,
                            status_code=200,
                            fetch_method="requests",
                            latency_ms=(time.perf_counter() - start_time) * 1000.0,
                            from_cache=False,
                        )
                        self._log_execution_diagnostics(url, res)
                        return res

                    elif status_code == 429:
                        retry_count += 1
                        retry_after = headers.get("Retry-After") if headers else None
                        await self.rate_limiter.handle_retry_after(domain, retry_after, retry_count)
                        continue

                    elif status_code in (403, 401):
                        logger.warning("Access denied (403/401); escalating to Playwright browser context", url=url)
                        self.rate_limiter.release(domain)
                        context.preferred_fetch_method = "playwright"
                        res = await self._fetch_via_playwright(url, start_time)
                        self._log_execution_diagnostics(url, res)
                        return res

                    elif status_code in (404, 410):
                        logger.error("Resource not found", status=status_code, url=url)
                        self.rate_limiter.release(domain)
                        res = FetchResult(
                            success=False,
                            status_code=status_code,
                            fetch_method="requests",
                            latency_ms=(time.perf_counter() - start_time) * 1000.0,
                            from_cache=False,
                            error=MCPError(
                                code=ErrorCode.NOT_FOUND,
                                message=f"URL page was not found: {status_code}",
                                retryable=False,
                            ),
                        )
                        self._log_execution_diagnostics(url, res)
                        return res
                    else:
                        # General status errors
                        logger.warning("Uncommon status response; retrying", status=status_code)
                        retry_count += 1
                        await self.rate_limiter.backoff(domain, retry_count)
                        continue

                except Exception as e:
                    logger.error("HTTP GET task raised exception; retrying", error=str(e))
                    retry_count += 1
                    await self.rate_limiter.backoff(domain, retry_count)

            # If retries exhausted, escalate to Playwright browser context
            logger.warning("HTTP requests fetch failed or exhausted; escalating to Playwright", url=url)
            self.rate_limiter.release(domain)
            context.preferred_fetch_method = "playwright"
            res = await self._fetch_via_playwright(url, start_time)
            self._log_execution_diagnostics(url, res)
            return res

        except Exception as outer_err:
            logger.error("Smart fetch outer handler exception; escalating to Playwright", error=str(outer_err))
            try:
                self.rate_limiter.release(domain)
            except Exception:
                pass
            context.preferred_fetch_method = "playwright"
            res = await self._fetch_via_playwright(url, start_time)
            self._log_execution_diagnostics(url, res)
            return res

    async def _fetch_via_playwright(self, url: str, start_time: float) -> FetchResult:
        """Helper to invoke Playwright render wrapper."""
        instructions = BrowserInstructions(
            wait_for_selector=self.config.browser.wait_for_selector,
            scroll_to_bottom=True,
            timeout_ms=self.config.browser.timeout_ms,
        )
        res = await self.playwright.render(url, instructions)
        latency = (time.perf_counter() - start_time) * 1000.0

        if res.success and res.html:
            await self.cache.set(url, res.html)
            return FetchResult(
                success=True,
                html=res.html,
                fetch_method="playwright",
                latency_ms=latency,
                from_cache=False,
            )
        else:
            return FetchResult(
                success=False,
                fetch_method="playwright",
                latency_ms=latency,
                from_cache=False,
                error=res.error or MCPError(code=ErrorCode.TIMEOUT, message="Playwright render failed"),
            )

    def _is_bot_challenge(self, html: str) -> bool:
        """Determines if the response is an empty challenge frame or bot wall."""
        if not html or len(html.strip()) < 500:
            return True
        
        lower_body = html.lower()
        challenge_markers = [
            "checking your browser",
            "cf-challenge",
            "ray id",
            "ddos-guard",
            "captcha",
            "hcaptcha",
            "g-recaptcha",
        ]
        return any(marker in lower_body for marker in challenge_markers)

    def _is_js_template(self, html: str) -> bool:
        """Detects if the HTML is a JS App Shell / Client-Side Rendered (CSR) template."""
        if not html:
            return True
        # Strip all whitespace from html and standardize single quotes to double quotes to make tag matches robust
        clean_html = "".join(html.split()).lower().replace("'", '"')
        csr_markers = [
            '<divid="root"></div>',
            '<divid="app"></div>',
            '<divid="__next"></div>',
            '<divid="v-app"></div>',
            '<app-root></app-root>',
            'noscript>youneedtoenablejavascript',
            'noscript>pleaseenablejavascript',
            'noscript>javascriptisrequired'
        ]
        return any(marker in clean_html for marker in csr_markers)

    def _log_execution_diagnostics(self, url: str, res: FetchResult) -> None:
        """Logs detailed execution and rendering diagnostics for auditing."""
        html = res.html or ""
        anchor_count = html.count("<a ")
        has_jsonld = "application/ld+json" in html
        has_cards = any(x in html.lower() for x in ["product-card", "product-item", "product-grid", "grid-item", "card-item"])
        
        logger.info(
            "\n"
            "====================================================\n"
            "               EXECUTION/RENDERING DIAGNOSTICS\n"
            "====================================================\n"
            f"URL:                      {url}\n"
            f"HTTP response status:     {res.status_code}\n"
            f"Response size:            {len(html)} bytes\n"
            f"CSR template detected:    {'Yes' if res.is_csr else 'No'}\n"
            f"Playwright escalation:    {'Yes' if res.fetch_method == 'playwright' else 'No'}\n"
            f"Rendered DOM size:        {len(html) if res.fetch_method == 'playwright' else 'N/A'}\n"
            f"Anchor count:             {anchor_count}\n"
            f"Structured data detected: {'Yes' if has_jsonld else 'No'}\n"
            f"Product cards detected:   {'Yes' if has_cards else 'No'}\n"
            f"Final extraction source:  {res.fetch_method.upper()}\n"
            "===================================================="
        )

    async def close(self) -> None:
        """Disposes sub-components."""
        await self.http_client.close()
        await self.playwright.close()
