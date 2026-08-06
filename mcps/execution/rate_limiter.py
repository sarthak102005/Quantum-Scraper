"""
mcps/execution/rate_limiter.py

RateLimiter — enforces per-domain semaphore execution limits, applies delay
jitter, exponential backoff, and parses Retry-After headers.
"""

from __future__ import annotations

import asyncio
import email.utils
import random
import time
from datetime import datetime

from shared.utils.config import Config, get_config
from shared.utils.logging import get_logger

logger = get_logger(__name__)


class RateLimiter:
    """Manages asynchronous domain-level queues and rate limit penalties."""

    def __init__(self, config: Config | None = None) -> None:
        self.config = config or get_config()
        self.semaphores: dict[str, asyncio.Semaphore] = {}
        self.lock = asyncio.Lock()

    async def _get_semaphore(self, domain: str) -> asyncio.Semaphore:
        """Lazily initialize per-domain semaphore thread-safely."""
        async with self.lock:
            if domain not in self.semaphores:
                limit = self.config.concurrency.max_requests_per_domain
                self.semaphores[domain] = asyncio.Semaphore(limit)
            return self.semaphores[domain]

    async def acquire(self, domain: str) -> None:
        """Acquire execution slot for a domain."""
        sem = await self._get_semaphore(domain)
        await sem.acquire()

    def release(self, domain: str) -> None:
        """Release slot back to domain pool."""
        if domain in self.semaphores:
            try:
                self.semaphores[domain].release()
            except ValueError:
                pass

    async def wait_with_jitter(self, domain: str) -> None:
        """Apply random delay jitter in range [min_ms, max_ms]."""
        delays = self.config.delays
        if delays.jitter:
            delay = random.uniform(delays.min_ms, delays.max_ms) / 1000.0
        else:
            delay = delays.min_ms / 1000.0

        logger.info("Applying delay jitter", domain=domain, seconds=delay)
        await asyncio.sleep(delay)

    async def backoff(self, domain: str, attempt: int) -> None:
        """Apply exponential backoff capped at 60 seconds."""
        factor = self.config.retries.backoff_factor
        delay = min(factor ** attempt, 60.0)
        logger.warning("Backoff active", domain=domain, attempt=attempt, seconds=delay)
        await asyncio.sleep(delay)

    async def handle_retry_after(self, domain: str, retry_after_header: str | None, attempt: int) -> None:
        """Evaluate retry-after header value (seconds or delta timestamp) or default to backoff.

        Args:
            domain: Domain target.
            retry_after_header: Optional Retry-After HTTP header string value.
            attempt: Number of attempts.
        """
        if not retry_after_header:
            await self.backoff(domain, attempt)
            return

        delay = 0.0
        header_val = retry_after_header.strip()

        # Case 1: Simple digit seconds
        if header_val.isdigit():
            delay = float(header_val)
        else:
            # Case 2: HTTP timestamp string
            try:
                parsed_time = email.utils.parsedate_to_datetime(header_val)
                delay = max((parsed_time - datetime.now(parsed_time.tzinfo)).total_seconds(), 0.0)
            except Exception:
                # Default backoff fallback
                await self.backoff(domain, attempt)
                return

        # Caps delay to max 60s to prevent hanging indefinite tasks
        delay = min(delay, 60.0)
        logger.warning("Respecting Retry-After header delay", domain=domain, seconds=delay)
        await asyncio.sleep(delay)
