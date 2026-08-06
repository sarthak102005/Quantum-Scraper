"""
tests/unit/test_extraction_mcp.py

Unit tests for 5-stage Extraction MCP pipeline.
"""

from __future__ import annotations

import pytest

from mcps.extraction.extraction_mcp import ExtractionMCP
from shared.models.website_profile import SelectorSet, WebsiteProfile
from shared.utils.config import get_config


@pytest.mark.asyncio
async def test_extraction_pipeline() -> None:
    config = get_config()
    extraction = ExtractionMCP(config)

    # 1. Load HTML fixture
    with open("tests/fixtures/sample_product.html", "r", encoding="utf-8") as f:
        html = f.read()

    # Domain context
    profile = WebsiteProfile(
        domain="example-shop.com",
        seed_url="https://example-shop.com/product/headphones",
    )

    # Stage 1 test: JSON-LD extraction
    result = await extraction.extract(html, profile)

    assert result.success is True
    assert result.method == "jsonld"
    assert result.confidence >= 0.90
    assert result.product is not None
    assert result.product.title == "Wireless Headphones Pro"
    assert result.product.price == 149.99
    assert result.product.currency == "USD"
    assert result.product.brand == "SoundMax"
    assert result.product.sku == "WHP-001"

    # Stage 2 test: CSS selector extraction
    # Remove json-ld from html to test selectors
    import re
    html_no_jsonld = re.sub(r"<script type=\"application/ld\+json\">([\s\S]*?)</script>", "", html)

    # Inject selectors into profile
    profile.selector_version = "v1"
    profile.selector_sets = [
        SelectorSet(
            version="v1",
            selectors={
                "title": {"css": "h1.product-title"},
                "price": {"css": ".pricing span.price", "transform": "to_float"},
                "currency": {"css": "meta[property='og:price:currency']"},
                "brand": {"css": "span.brand"},
                "availability": {"css": ".availability.in-stock span"},
            },
        )
    ]

    result_css = await extraction.extract(html_no_jsonld, profile)
    assert result_css.success is True
    assert result_css.method == "css"
    assert result_css.product.title == "Wireless Headphones Pro"
    assert result_css.product.price == 149.99
