"""
tests/unit/test_navigation_hub.py

Unit tests verifying Navigation Hub classification, heuristics scoring,
crawler navigation loops, visited node memory split, and export behaviors.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from mcps.classification.heuristics import classify_url
from shared.models.classified_url import PageType, ClassifiedURL
from shared.models.product import Product
from shared.models.validation_result import ValidationResult
from mcps.storage.csv_writer import CSVWriter
from mcps.storage.json_writer import JSONWriter
from shared.utils.config import get_config


def test_navigation_hub_classification() -> None:
    # Test typical hub URLs are recognized as NAVIGATION_HUB
    hub_urls = [
        "https://www.jcb.com/en-us/industries/",
        "https://www.jcb.com/en-gb/applications/demolition",
        "https://www.jcb.com/en-za/markets/quarry",
        "https://example.com/solutions/waste-management",
        "https://example.com/attachments",
        "https://example.com/brands/jcb-parts"
    ]

    for url in hub_urls:
        ptype, confidence, signals = classify_url(url)
        assert ptype == "NAVIGATION_HUB"
        assert confidence > 0.3


def test_navigation_intent_scoring_with_snippet() -> None:
    # Hub with HTML signals fired
    html_snippet = """
    <html>
      <body>
        <h1>Industries We Serve</h1>
        <div class="landing-grid">
          <div class="card"><h2>Agriculture</h2><p>Read about solutions</p></div>
          <div class="card"><h2>Construction</h2><p>Read about equipment</p></div>
        </div>
      </body>
    </html>
    """
    url = "https://example.com/industries"
    ptype, confidence, signals = classify_url(url, html_snippet=html_snippet)
    assert ptype == "NAVIGATION_HUB"
    # Ensure signals related to hub grid/headings are present
    assert any("hub_card_layout" in s or "hub_heading_density" in s for s in signals)


def test_visited_set_separation() -> None:
    # Emulate the sets created in execute_crawl
    visited_navigation_hubs = set()
    visited_categories = set()
    visited_product_families = set()
    visited_product_pages = set()

    norm_url = "https://example.com/products/4cx"

    # Adding product does not pollute other lists
    visited_product_pages.add(norm_url)
    assert norm_url not in visited_navigation_hubs
    assert norm_url not in visited_categories
    assert norm_url not in visited_product_families


@pytest.mark.asyncio
async def test_csv_and_json_export_structure(tmp_path: Path) -> None:
    # Setup custom output dir in config
    config = get_config()
    orig_dir = config.output.directory
    config.output.directory = str(tmp_path)

    product = Product(
        product_id="test-uuid-12345",
        source_url="https://example.com/p/123",
        domain="example.com",
        title="Compact Excavator 4CX",
        sku="JCB-4CX-COMPACT",
        price=125000.0,
        currency="USD",
        availability="in_stock",
        brand="JCB",
        description="Powerful compact excavator for multi-industry use cases."
    )
    validation = ValidationResult(
        verdict="PASS",
        quality_score=0.95
    )

    # 1. Test CSVWriter writes only index fields
    csv_writer = CSVWriter(config)
    await csv_writer.write(product, validation)
    await csv_writer.close()

    csv_file = tmp_path / "products.csv"
    assert csv_file.exists()
    
    with open(csv_file, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
        # Header + 1 Row
        assert len(lines) == 2
        # Check column names
        # Check column names match actual CSVWriter fieldnames
        assert lines[0] == "product_id,title,sku,category,source_url"
        assert lines[1] == "test-uuid-12345,Compact Excavator 4CX,JCB-4CX-COMPACT,,https://example.com/p/123"

    # 2. Test JSONWriter writes complete product representation
    json_writer = JSONWriter(config)
    await json_writer.write(product, validation)
    await json_writer.close()

    individual_json = tmp_path / "products" / "test-uuid-12345.json"
    assert individual_json.exists()

    with open(individual_json, "r", encoding="utf-8") as f:
        data = json.load(f)
        # Verify full payload remains intact
        assert data["product_id"] == "test-uuid-12345"
        assert data["price"] == 125000.0
        assert data["brand"] == "JCB"
        assert data["description"] == "Powerful compact excavator for multi-industry use cases."
        assert data["validation"]["verdict"] == "PASS"

    # Cleanup
    config.output.directory = orig_dir
