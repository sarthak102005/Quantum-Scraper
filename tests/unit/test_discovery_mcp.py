"""
tests/unit/test_discovery_mcp.py

Unit tests for Discovery MCP robots.txt and sitemap parsing.
"""

from __future__ import annotations

import pytest
from aioresponses import aioresponses

from mcps.discovery.discovery_mcp import DiscoveryMCP
from shared.models.crawl_task import CrawlTask
from shared.utils.config import get_config


@pytest.mark.asyncio
async def test_discovery_mcp_flow() -> None:
    config = get_config()
    discovery = DiscoveryMCP(config)

    task = CrawlTask(
        seed_url="https://example-shop.com",
        domain="example-shop.com",
        max_pages=10,
    )

    # Read fixtures
    with open("tests/fixtures/sample_robots.txt", "r", encoding="utf-8") as f:
        robots_txt = f.read()

    with open("tests/fixtures/sample_sitemap.xml", "r", encoding="utf-8") as f:
        sitemap_xml = f.read()

    with aioresponses() as m:
        m.get("https://example-shop.com/robots.txt", status=200, body=robots_txt)
        m.get("https://example-shop.com/sitemap.xml", status=200, body=sitemap_xml)
        m.get("https://example-shop.com/sitemap_products.xml", status=404)

        result = await discovery.discover(task)

        assert result.profile is not None
        assert result.profile.domain == "example-shop.com"
        assert len(result.profile.robots_disallow) == 8
        assert len(result.urls) > 0
        assert "https://example-shop.com/product/wireless-headphones-pro" in result.urls
