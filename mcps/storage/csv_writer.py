"""
mcps/storage/csv_writer.py

CSV Writer — appends extracted products directly to a flat CSV file
without memory buffering.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import asyncio

from shared.models.product import Product
from shared.models.validation_result import ValidationResult
from shared.utils.config import Config, get_config
from shared.utils.logging import get_logger

logger = get_logger(__name__)


class CSVWriter:
    """Appends records immediately to CSV targets using thread-safe locks."""

    def __init__(self, config: Config | None = None) -> None:
        self.config = config or get_config()
        self.lock = asyncio.Lock()
        self.output_path = Path(self.config.output.directory) / "products.csv"
        self._headers_written = False

    async def write(self, product: Product, validation: ValidationResult) -> None:
        """Serialize and append product record.

        Args:
            product: Product model instance.
            validation: ValidationResult matching the product.
        """
        async with self.lock:
            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            write_headers = not self.output_path.exists()

            row = {
                "product_id":  product.product_id,
                "title":       product.title,
                "sku":         product.sku,
                "category":    product.category,
                "source_url":  product.source_url,
            }

            try:
                # Open in append mode with encoding UTF-8
                with open(self.output_path, "a", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=row.keys())
                    if write_headers:
                        writer.writeheader()
                    writer.writerow(row)
            except Exception as e:
                logger.error("Failed writing product to CSV file", error=str(e), path=str(self.output_path))

    async def flush(self) -> None:
        """No-op: CSV file is appended immediately on write()."""
        pass

    async def close(self) -> None:
        """No-op for CSV append streams."""
        pass
