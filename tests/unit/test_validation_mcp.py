"""
tests/unit/test_validation_mcp.py

Unit tests for Validation MCP schema constraints.
"""

from __future__ import annotations

import pytest

from mcps.validation.validation_mcp import ValidationMCP
from shared.models.extraction_result import ExtractionResult
from shared.models.product import Product


@pytest.mark.asyncio
async def test_product_validation() -> None:
    validator = ValidationMCP()

    # Case 1: valid product
    p_valid = Product(
        source_url="https://example.com/p/1",
        domain="example.com",
        title="Valid Product",
        price=10.99,
        currency="USD",
        brand="BrandA",
        availability="in_stock",
        sku="SKU-100",
        specifications={"Power": "120V"},
    )
    res_valid = ExtractionResult(success=True, product=p_valid, confidence=0.90, method="jsonld")
    
    val_res = await validator.validate(res_valid)
    assert val_res.verdict == "PASS"
    assert val_res.quality_score > 0.8
    assert len(val_res.errors) == 0

    # Case 2: invalid product (missing fields)
    p_invalid = Product(
        source_url="https://example.com/p/1",
        domain="example.com",
        title=None,  # Missing
        price=None,
        currency="USD",
        brand="BrandA",
        availability="in_stock",
        # specifications is missing/empty, which is also a validation failure now
    )
    res_invalid = ExtractionResult(success=True, product=p_invalid, confidence=0.90, method="jsonld")
    
    val_res_inv = await validator.validate(res_invalid)
    assert val_res_inv.verdict == "FAIL"
    assert len(val_res_inv.errors) == 1
    assert val_res_inv.retry_recommended is True

    # Case 3: duplicate check
    p_dup = Product(
        source_url="https://example.com/p/2",
        domain="example.com",
        title="Valid Product 2",
        price=12.99,
        currency="USD",
        brand="BrandA",
        availability="in_stock",
        sku="SKU-100",  # Duplicate SKU
        specifications={"Power": "120V"},
    )
    res_dup = ExtractionResult(success=True, product=p_dup, confidence=0.90, method="jsonld")
    val_res_dup = await validator.validate(res_dup)
    assert val_res_dup.verdict == "WARN"
    assert val_res_dup.is_duplicate is True
