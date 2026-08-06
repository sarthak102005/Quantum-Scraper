"""
tests/unit/test_evidence_classification.py

Unit tests verifying evidence-based classification logic, scoring weights,
combos, and category page exclusions.
"""

from __future__ import annotations

import pytest
from mcps.classification.heuristics import classify_url
from shared.models.website_profile import WebsiteProfile
from shared.utils.config import get_config


def test_evidence_weights_and_combos() -> None:
    profile = WebsiteProfile(domain="example-shop.com", seed_url="https://example-shop.com")
    config = get_config()
    config.classification.threshold = 60

    # Case 1: Pure B2B with no price but SKU, Add to Cart, specifications, and request quote
    html_b2b = """
    <html>
        <body>
            <h1>Excavator EX300</h1>
            <span class="sku">Model SKU-EX300</span>
            <button id="add-to-cart">Add to Cart</button>
            <div class="specs">Specifications: Weight: 30 tons, Power: 250hp</div>
            <button class="quote">Request a Quote</button>
        </body>
    </html>
    """
    url = "https://example-shop.com/products/excavator-ex300"
    ptype, confidence, signals = classify_url(url, html_snippet=html_b2b, profile=profile)

    assert ptype == "PRODUCT"
    assert confidence > 0.8
    assert any("sku_present" in s for s in signals)
    assert any("add_to_cart" in s for s in signals)
    assert any("request_quote" in s for s in signals)
    assert any("specs_present" in s for s in signals)

    # Case 2: Category page containing prices but heavily penalized by grid, pagination, and filter signals
    html_category = """
    <html>
        <body>
            <h1>Excavators Catalog</h1>
            <div class="product-grid">
                <div class="card">Product 1 - $1000</div>
                <div class="card">Product 2 - $2000</div>
            </div>
            <div class="pagination">
                <a href="?page=2">Next Page</a>
            </div>
            <div class="filter-sidebar">
                Filter by weight
            </div>
            <select class="sort-by">
                <option>Sort by price</option>
            </select>
        </body>
    </html>
    """
    cat_url = "https://example-shop.com/category/excavators"
    ptype_cat, confidence_cat, signals_cat = classify_url(cat_url, html_snippet=html_category, profile=profile)

    assert ptype_cat == "CATEGORY"
    assert any("category_grid" in s for s in signals_cat)
    assert any("pagination_controls" in s for s in signals_cat)
    assert any("filters_sorting" in s for s in signals_cat)

    # Case 3: Nested root category paths (e.g. JCB machine category URLs)
    jcb_cat_url = "https://www.jcb.com/en-GB/products/machines/agricultural-tractors/"
    ptype_jcb, confidence_jcb, signals_jcb = classify_url(jcb_cat_url, profile=profile)
    assert ptype_jcb == "CATEGORY"

    # Case 4: Singular models without digits (e.g. Husqvarna ceora)
    husq_url = "https://www.husqvarna.com/at/maehroboter/ceora/"
    ptype_husq, confidence_husq, signals_husq = classify_url(husq_url, profile=profile)
    assert ptype_husq == "UNKNOWN"
    
    # If the root is /products/, it matches Deep Catalog Leaf and gets score 25
    husq_prod_url = "https://www.husqvarna.com/en/products/lawnmowers/ceora"
    ptype_husq_prod, confidence_husq_prod, signals_husq_prod = classify_url(husq_prod_url, profile=profile)
    assert ptype_husq_prod == "PRODUCT"

    # Case 5: Non-catalog events/blogs (e.g. JCB events)
    jcb_event_url = "https://www.jcb.com/en-GB/explore/engage/events/2026/02/exec-hire-show-2026/"
    ptype_event, confidence_event, signals_event = classify_url(jcb_event_url, profile=profile)
    # Exclusions should penalize PRODUCT and CATEGORY, defaulting to UNKNOWN or non-catalog types
    assert ptype_event in ("UNKNOWN", "NEWS", "BLOG")
