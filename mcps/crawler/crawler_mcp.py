"""
mcps/crawler/crawler_mcp.py

Crawler MCP — controls traversal queue order, checkpoints, restoration,
and enforces budget constraints.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcps.crawler.queue_manager import QueueManager
from shared.models.classified_url import ClassifiedURL
from shared.models.crawl_task import CrawlTask
from shared.utils.config import Config, get_config
from shared.utils.logging import get_logger

logger = get_logger(__name__)


class CrawlerMCP:
    """Orchestrates BFS/DFS crawl traversals and state checkpoints."""

    def __init__(self, task: CrawlTask, config: Config | None = None) -> None:
        self.task = task
        self.config = config or get_config()
        self.queue = QueueManager(max_budget=task.max_pages)
        self.checkpoint_dir = Path(self.config.output.directory) / "checkpoints" / task.task_id

    async def enqueue(self, urls: list[ClassifiedURL]) -> None:
        """Enqueue classified URLs.

        Args:
            urls: List of ClassifiedURL objects.
        """
        count = await self.queue.enqueue(urls)
        logger.info("Enqueued classified URLs", enqueued=count, stats=self.queue.stats())

    async def next_batch(self, size: int) -> list[ClassifiedURL]:
        """Fetch next batch of URLs for processing.

        Args:
            size: Size of batch.

        Returns:
            List of ClassifiedURL items.
        """
        return await self.queue.next_batch(size)

    async def mark_completed(self, url: str) -> None:
        """Mark page as completed."""
        await self.queue.mark_completed(url)

    async def mark_failed(self, url: str, error: str) -> None:
        """Mark page as failed."""
        await self.queue.mark_failed(url, error)

    async def checkpoint(self) -> None:
        """Serialize queue state to checkpoints directory."""
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        path = self.checkpoint_dir / f"checkpoint_{int(Path('.').stat().st_mtime)}.json"

        state = self.queue.get_state()
        state["task_id"] = self.task.task_id
        state["domain"] = self.task.domain

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
            logger.info("Saved crawl queue checkpoint", path=str(path))
        except Exception as e:
            logger.error("Failed to save crawl checkpoint", error=str(e))

    async def restore(self, checkpoint_path: str) -> None:
        """Restore state from file in an idempotent manner.

        Args:
            checkpoint_path: Path to the checkpoint JSON file.
        """
        logger.info("Restoring queue from checkpoint", path=checkpoint_path)
        try:
            with open(checkpoint_path, "r", encoding="utf-8") as f:
                state = json.load(f)
            self.queue.set_state(state)
            logger.info("Queue restore complete", stats=self.queue.stats())
        except Exception as e:
            logger.error("Failed to restore from checkpoint", error=str(e))

    def stats(self) -> dict[str, int]:
        """Return crawl queue stats."""
        return self.queue.stats()
