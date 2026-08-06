"""
tests/unit/test_classification_mcp.py

Unit tests for page classification heuristics.
"""

from __future__ import annotations

import pytest

from mcps.classification.classification_mcp import ClassificationMCP
from shared.models.website_profile import WebsiteProfile


@pytest.mark.asyncio
async def test_url_classification() -> None:
    classification = ClassificationMCP()
    profile = WebsiteProfile(domain="example-shop.com", seed_url="https://example-shop.com")

    urls = [
        "https://example-shop.com/",
        "https://example-shop.com/product/soundmax-headphones-pro",
        "https://example-shop.com/category/electronics",
        "https://example-shop.com/category/electronics?page=2",
        "https://example-shop.com/about-us",
    ]

    classified = await classification.classify(urls, profile)

    assert len(classified) == 5
    
    # Home check
    assert classified[0].page_type == "LANDING_PAGE"
    
    # Product check
    assert classified[1].page_type == "PRODUCT"
    assert classified[1].priority == 3
    
    # Category check
    assert classified[2].page_type == "CATEGORY"
    assert classified[2].priority == 1

    # Pagination check
    assert classified[3].page_type == "CATEGORY"
    assert classified[3].priority == 1

    # Unknown page check
    assert classified[4].page_type == "UNKNOWN"
