"""
mcps/crawler/queue_manager.py

QueueManager — manages state for pending, active, completed, and failed
URLs under concurrency and budget constraints.
"""

from __future__ import annotations

import asyncio
from typing import Any

from shared.models.classified_url import ClassifiedURL
from shared.utils.logging import get_logger
from shared.utils.url_normalizer import normalize_url

logger = get_logger(__name__)


class QueueManager:
    """Synchronized crawling queue tracking states."""

    def __init__(self, max_budget: int = 100) -> None:
        self.max_budget = max_budget
        self.lock = asyncio.Lock()

        # Queues
        # list of (priority, ClassifiedURL)
        self._pending: list[ClassifiedURL] = []
        self._active: set[str] = set()
        self._completed: set[str] = set()
        self._failed: list[dict[str, str]] = []

    async def enqueue(self, urls: list[ClassifiedURL]) -> int:
        """Add unique URLs to the pending queue respecting budget limit.

        Args:
            urls: ClassifiedURL list to evaluate.

        Returns:
            Number of new URLs enqueued.
        """
        async with self.lock:
            enqueued_count = 0
            for item in urls:
                # Normalize URL
                item.url = normalize_url(item.url)
                url = item.url
                
                # Deduplication check across all states
                if (
                    url in self._active
                    or url in self._completed
                    or any(f["url"] == url for f in self._failed)
                    or any(p.url == url for p in self._pending)
                ):
                    continue

                # Budget check
                total_processed = len(self._completed) + len(self._active) + len(self._pending)
                if total_processed >= self.max_budget:
                    logger.info("Crawl budget limit hit; dropping further enqueues", max_budget=self.max_budget)
                    break

                self._pending.append(item)
                enqueued_count += 1

            # Sort pending based on priority descending, then confidence descending, then depth descending
            self._pending.sort(key=lambda x: (x.priority, x.confidence, x.depth), reverse=True)
            return enqueued_count

    async def next_batch(self, size: int) -> list[ClassifiedURL]:
        """Fetch next batch of URLs and transition them to active state.

        Args:
            size: Size of batch to extract.

        Returns:
            List of ClassifiedURL models.
        """
        async with self.lock:
            batch: list[ClassifiedURL] = []
            while len(batch) < size and self._pending:
                item = self._pending.pop(0)
                self._active.add(item.url)
                batch.append(item)
            return batch

    async def mark_completed(self, url: str) -> None:
        """Move URL from active to completed.

        Args:
            url: Page URL completed.
        """
        async with self.lock:
            self._active.discard(url)
            self._completed.add(url)

    async def mark_failed(self, url: str, error: str) -> None:
        """Move URL from active to failed.

        Args:
            url: Page URL failed.
            error: Error message context.
        """
        async with self.lock:
            self._active.discard(url)
            # Avoid duplicate logs in failed list
            if not any(f["url"] == url for f in self._failed):
                self._failed.append({"url": url, "error": error})

    def stats(self) -> dict[str, int]:
        """Return state totals."""
        return {
            "pending": len(self._pending),
            "active": len(self._active),
            "completed": len(self._completed),
            "failed": len(self._failed),
        }

    def get_state(self) -> dict[str, Any]:
        """Export state for checkpoint serialization."""
        import json
        return {
            "pending": [json.loads(item.model_dump_json()) for item in self._pending],
            "active": list(self._active),
            "completed": list(self._completed),
            "failed": self._failed,
        }

    def set_state(self, state: dict[str, Any]) -> None:
        """Import state from checkpoint serialization."""
        self._pending = [ClassifiedURL(**item) for item in state.get("pending", [])]
        self._active = set(state.get("active", []))
        self._completed = set(state.get("completed", []))
        self._failed = state.get("failed", [])
