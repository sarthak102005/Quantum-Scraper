"""
mcps/storage/json_writer.py

JSON Writer — serializes products to a streaming line-delimited JSON file
(NDJSON) to minimize memory foot-print.
"""

from __future__ import annotations

import json
from pathlib import Path

import asyncio

from shared.models.product import Product
from shared.models.validation_result import ValidationResult
from shared.utils.config import Config, get_config
from shared.utils.logging import get_logger

logger = get_logger(__name__)


class JSONWriter:
    """Appends records immediately to NDJSON target logs and exports individual canonical JSON files."""

    def __init__(self, config: Config | None = None) -> None:
        self.config = config or get_config()
        self.lock = asyncio.Lock()
        self.output_path = Path(self.config.output.directory) / "products.ndjson"
        self.individual_dir = Path(self.config.output.directory) / "products"

    async def write(self, product: Product, validation: ValidationResult) -> None:
        """Appends serialized model to NDJSON file and writes individual canonical JSON."""
        async with self.lock:
            # Ensure directories exist
            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            self.individual_dir.mkdir(parents=True, exist_ok=True)

            data = product.model_dump()
            # Convert datetime items to ISO format strings
            data["extracted_at"] = product.extracted_at.isoformat()
            data["validation"] = {
                "verdict": validation.verdict,
                "quality_score": validation.quality_score,
            }

            # 1. Write individual canonical JSON file pretty printed
            individual_file = self.individual_dir / f"{product.product_id}.json"
            try:
                with open(individual_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
            except Exception as e:
                logger.error("Failed writing individual canonical JSON file", error=str(e), path=str(individual_file))

            # 2. Append to NDJSON flat log file
            try:
                with open(self.output_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(data, ensure_ascii=False) + "\n")
            except Exception as e:
                logger.error("Failed writing product to NDJSON file", error=str(e), path=str(self.output_path))

    async def flush(self) -> None:
        """No-op."""
        pass

    async def close(self) -> None:
        """No-op."""
        pass
