"""
mcps/execution/http_client.py

HTTPClient — handles low-level async HTTP fetches using connection pools,
User-Agent rotation, proxy setup, and browser header emulation.
"""

from __future__ import annotations

import random
from typing import Any

import aiohttp

from shared.utils.config import Config, get_config
from shared.utils.logging import get_logger

logger = get_logger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
]


class HTTPClient:
    """Connection-pooled Client wrapping aiohttp Session operations."""

    def __init__(self, config: Config | None = None) -> None:
        self.config = config or get_config()
        self._session: aiohttp.ClientSession | None = None

    def _get_session(self) -> aiohttp.ClientSession:
        """Lazily initialize ClientSession with default timeouts and pooling."""
        if self._session is None or self._session.closed:
            # Set up default connection pooling limits
            connector = aiohttp.TCPConnector(
                limit=self.config.concurrency.global_max_requests,
                ttl_dns_cache=300,
            )
            self._session = aiohttp.ClientSession(
                connector=connector,
                cookie_jar=aiohttp.CookieJar(unsafe=True),
            )
        return self._session

    async def get(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout_ms: int = 30000,
    ) -> tuple[int, str, dict[str, str]]:
        """Make an async HTTP GET request.

        Args:
            url: Absolute URL target.
            headers: Optional headers override.
            timeout_ms: Connection and read timeout in milliseconds.

        Returns:
            tuple containing (status_code, body_string, response_headers).
        """
        session = self._get_session()

        # Build headers mimicking standard browser profile
        req_headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
        }
        if headers:
            req_headers.update(headers)

        proxy = None
        if self.config.proxies.enabled and self.config.proxies.pool:
            proxy = random.choice(self.config.proxies.pool)

        timeout = aiohttp.ClientTimeout(total=timeout_ms / 1000.0)

        logger.info("Executing HTTP GET", url=url, proxy=proxy)
        async with session.get(
            url,
            headers=req_headers,
            proxy=proxy,
            timeout=timeout,
            allow_redirects=True,
        ) as resp:
            body = await resp.text(errors="replace")
            # Convert multidict headers to flat string dict
            resp_headers = {str(k): str(v) for k, v in resp.headers.items()}
            return resp.status, body, resp_headers

    async def close(self) -> None:
        """Close the active ClientSession pool."""
        if self._session and not self._session.closed:
            await self._session.close()
            logger.info("HTTP client session pool closed")
