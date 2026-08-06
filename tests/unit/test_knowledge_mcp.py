"""
tests/unit/test_knowledge_mcp.py

Unit tests for Knowledge MCP SQLite persistence, selector version rollbacks,
and rolling statistical learning adjustments.
"""

from __future__ import annotations

import os
import pytest
from pathlib import Path

from mcps.knowledge.knowledge_mcp import KnowledgeMCP
from shared.models.crawl_statistics import CrawlStatistics
from shared.models.website_profile import WebsiteProfile
from shared.utils.config import get_config


@pytest.mark.asyncio
async def test_knowledge_learning_flow() -> None:
    config = get_config()
    test_db = "outputs/test_knowledge.db"
    
    # Init MCP
    knowledge = KnowledgeMCP(test_db)
    await knowledge.init()

    domain = "example-shop.com"
    profile = WebsiteProfile(domain=domain, seed_url="https://example-shop.com")

    # 1. Save and retrieve test profile
    await knowledge.save_profile(profile)
    fetched = await knowledge.get_profile(domain)
    assert fetched is not None
    assert fetched.domain == domain
    assert fetched.preferred_fetch_method == "requests"

    # 2. Simulate crawl stats run updates (Playwright high load ratio)
    stats = CrawlStatistics(task_id="task-123", domain=domain)
    stats.total_fetched = 10
    stats.playwright_fetches = 8  # 80% Playwright fetches
    stats.average_latency_ms = 450.0
    stats.rate_limit_events = 1  # decrements concurrency

    await knowledge.update_from_crawl(stats, profile)

    # 3. Verify recommendations adjusted profile parameters
    recs = await knowledge.get_recommendations(domain)
    assert recs.preferred_fetch_method == "playwright"
    assert recs.recommended_concurrency == 2  # Concurrency decremented from 3 -> 2

    # Close store
    await knowledge.close()

    # Clean up test DB file
    if Path(test_db).exists():
        os.remove(test_db)
