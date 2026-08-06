"""
mcps/execution/cache.py

Cache — thread-safe response cache using OrderedDict for LRU evictions
and custom TTL expirations.
"""

from __future__ import annotations

import asyncio
import sys
import time
from collections import OrderedDict
from dataclasses import dataclass

from shared.utils.config import Config, get_config
from shared.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class CacheEntry:
    html: str
    timestamp: float
    size_bytes: int


class Cache:
    """In-memory size-bounded response cache with LRU eviction."""

    def __init__(self, config: Config | None = None) -> None:
        self.config = config or get_config()
        self.lock = asyncio.Lock()
        self.store: OrderedDict[str, CacheEntry] = OrderedDict()
        self.current_size_bytes = 0

        self.hits = 0
        self.misses = 0

    async def get(self, url: str) -> str | None:
        """Fetch page source from cache if hit and not expired.

        Args:
            url: Page URL.

        Returns:
            Page source string or None.
        """
        if not self.config.cache.enabled:
            return None

        async with self.lock:
            if url not in self.store:
                self.misses += 1
                return None

            entry = self.store[url]
            # Check expiration (TTL)
            if time.time() - entry.timestamp > self.config.cache.ttl_seconds:
                logger.info("Cache entry expired", url=url)
                # Expire item
                self.current_size_bytes -= entry.size_bytes
                del self.store[url]
                self.misses += 1
                return None

            # Move to end (MRU)
            self.store.move_to_end(url)
            self.hits += 1
            return entry.html

    async def set(self, url: str, html: str) -> None:
        """Store page source inside cache.

        Evicts LRU entries if current_size_bytes exceeds max_size_mb limit.

        Args:
            url: Page URL key.
            html: HTML page source value.
        """
        if not self.config.cache.enabled:
            return

        async with self.lock:
            size_bytes = sys.getsizeof(html)
            
            # If already exists, overwrite size offset
            if url in self.store:
                self.current_size_bytes -= self.store[url].size_bytes

            self.store[url] = CacheEntry(
                html=html,
                timestamp=time.time(),
                size_bytes=size_bytes,
            )
            self.store.move_to_end(url)
            self.current_size_bytes += size_bytes

            # Evict entries until size boundary is respected
            max_bytes = self.config.cache.max_size_mb * 1024 * 1024
            evicted_count = 0
            while self.current_size_bytes > max_bytes and self.store:
                _, oldest_entry = self.store.popitem(last=False)
                self.current_size_bytes -= oldest_entry.size_bytes
                evicted_count += 1

            if evicted_count > 0:
                logger.info("Evicted items from cache", count=evicted_count, current_size_mb=self.size_mb())

    async def invalidate(self, url: str) -> None:
        """Manually remove an entry."""
        async with self.lock:
            if url in self.store:
                entry = self.store.pop(url)
                self.current_size_bytes -= entry.size_bytes

    def size_mb(self) -> float:
        """Current cache size in MB."""
        return self.current_size_bytes / (1024 * 1024)

    def stats(self) -> dict[str, object]:
        """Collect usage statistics."""
        return {
            "enabled": self.config.cache.enabled,
            "hits": self.hits,
            "misses": self.misses,
            "entries_count": len(self.store),
            "size_mb": self.size_mb(),
        }
