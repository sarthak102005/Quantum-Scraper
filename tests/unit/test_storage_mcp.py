"""
tests/unit/test_storage_mcp.py

Unit tests for CSV, NDJSON, and SQLite storage writer drivers.
"""

from __future__ import annotations

from pathlib import Path
import pytest

from mcps.storage.storage_mcp import StorageMCP
from shared.models.product import Product
from shared.models.validation_result import ValidationResult
from shared.utils.config import get_config


@pytest.mark.asyncio
async def test_storage_writers(tmp_path: Path) -> None:
    config = get_config()
    orig_dir = config.output.directory
    config.output.directory = str(tmp_path)

    try:
        storage = StorageMCP(config)

        product = Product(
            source_url="https://example.com/p/1",
            domain="example.com",
            title="Storage Test Product",
            price=9.99,
            currency="USD",
            brand="BrandStore",
            availability="in_stock",
            sku="SKU-STORE",
        )
        validation = ValidationResult(verdict="PASS", quality_score=0.90)

        # Write files
        res = await storage.write(product, validation)
        assert res.success is True
        assert len(res.formats_written) == 3

        # Close writers
        await storage.close()

        # Check existence
        csv_file = tmp_path / "products.csv"
        json_file = tmp_path / "products.ndjson"
        db_file = tmp_path / "products.db"

        assert csv_file.exists()
        assert json_file.exists()
        assert db_file.exists()

    finally:
        config.output.directory = orig_dir
