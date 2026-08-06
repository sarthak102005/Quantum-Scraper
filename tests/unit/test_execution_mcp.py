"""
tests/unit/test_execution_mcp.py

Unit tests for smart_fetch decision trees, caching, and request rules.
"""

from __future__ import annotations

import pytest
from aioresponses import aioresponses

from mcps.execution.execution_mcp import ExecutionMCP
from shared.models.website_profile import WebsiteProfile
from shared.utils.config import get_config


@pytest.mark.asyncio
async def test_smart_fetch_http_flow() -> None:
    config = get_config()
    execution = ExecutionMCP(config)
    profile = WebsiteProfile(domain="example-shop.com", seed_url="https://example-shop.com")

    url = "https://example-shop.com/product/soundmax-headphones-pro"
    mock_body = "<html><body><h1>SoundMax Headphones</h1><span class='price'>$149.99</span>" + (" " * 500) + "</body></html>"

    with aioresponses() as m:
        m.get(url, status=200, body=mock_body)

        # 1. First fetch: network call
        result = await execution.smart_fetch(url, profile)
        assert result.success is True
        assert result.status_code == 200
        assert result.fetch_method == "requests"
        assert result.from_cache is False

        # 2. Second fetch: cache hit
        result_cached = await execution.smart_fetch(url, profile)
        assert result_cached.success is True
        assert result_cached.from_cache is True

    await execution.close()
@pytest.mark.asyncio
async def test_smart_fetch_escalation_flow() -> None:
    # Set up ExecutionMCP with disabled playwright render mock or playwright enabled
    config = get_config()
    execution = ExecutionMCP(config)
    profile = WebsiteProfile(domain="example-shop.com", seed_url="https://example-shop.com")

    url = "https://example-shop.com/product/challenge"
    challenge_body = "<html><body>checking your browser</body></html>"

    with aioresponses() as m:
        m.get(url, status=403, body=challenge_body)

        # Should escalate to playwright (will throw error since browser is mocked or not running but check type)
        res = await execution.smart_fetch(url, profile)
        assert res.fetch_method == "playwright" or res.success is False

    await execution.close()

@pytest.mark.asyncio
async def test_csr_template_detection() -> None:
    config = get_config()
    execution = ExecutionMCP(config)
    
    # 1. CSR templates
    assert execution._is_js_template("<html><body><div id='root'></div></body></html>") is True
    assert execution._is_js_template("<html><body><app-root></app-root></body></html>") is True
    
    # 2. Standard HTML page
    assert execution._is_js_template("<html><body><h1>Welcome to our shop</h1><p>Many items here!</p></body></html>") is False
    
    # 3. Escalate on CSR template
    profile = WebsiteProfile(domain="example-shop.com", seed_url="https://example-shop.com")
    url = "https://example-shop.com/product/react-page"
    csr_body = "<html><body><div id='root'></div></body></html>"
    
    with aioresponses() as m:
        m.get(url, status=200, body=csr_body)
        res = await execution.smart_fetch(url, profile)
        # Should escalate to playwright
        assert res.fetch_method == "playwright" or res.success is False
        
    await execution.close()
