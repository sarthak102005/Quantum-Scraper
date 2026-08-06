"""
tests/unit/test_crawler_mcp.py

Unit tests for Crawler MCP queue operations and checkpoint restoration.
"""

from __future__ import annotations

import os
import pytest
from pathlib import Path

from mcps.crawler.crawler_mcp import CrawlerMCP
from shared.models.classified_url import ClassifiedURL
from shared.models.crawl_task import CrawlTask
from shared.utils.config import get_config


@pytest.mark.asyncio
async def test_crawler_queue_manager_and_checkpoint() -> None:
    config = get_config()
    task = CrawlTask(
        seed_url="https://example-shop.com",
        domain="example-shop.com",
        max_pages=10,
    )

    crawler = CrawlerMCP(task, config)

    urls = [
        ClassifiedURL(url="https://example-shop.com/product/1", page_type="product", priority=3),
        ClassifiedURL(url="https://example-shop.com/category/1", page_type="category", priority=2),
        ClassifiedURL(url="https://example-shop.com/pagination/1", page_type="pagination", priority=1),
        ClassifiedURL(url="https://example-shop.com/product/2", page_type="product", priority=3),
    ]

    await crawler.enqueue(urls)

    # Next batch
    batch = await crawler.next_batch(2)
    assert len(batch) == 2
    # Product should be retrieved first due to priority (3)
    assert batch[0].page_type == "PRODUCT"
    assert batch[1].page_type == "PRODUCT"

    # Mark completed and checkpoint
    await crawler.mark_completed(batch[0].url)
    await crawler.checkpoint()

    # Find saved checkpoints
    checkpoints = list(Path(crawler.checkpoint_dir).glob("checkpoint_*.json"))
    assert len(checkpoints) > 0

    # Test restoration on new crawler instance
    new_crawler = CrawlerMCP(task, config)
    await new_crawler.restore(str(checkpoints[0]))

    stats = new_crawler.stats()
    assert stats["completed"] == 1
    assert stats["active"] == 1  # batch[1] is still active in state

    # Clean up checkpoint file
    for cp in checkpoints:
        os.remove(cp)
