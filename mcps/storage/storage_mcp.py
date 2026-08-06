"""
mcps/storage/storage_mcp.py

Storage MCP — coordinates streaming writes to CSV, NDJSON, and SQLite tables
simultaneously, ensuring no long-term memory accumulation.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from pydantic import BaseModel, Field

from mcps.storage.csv_writer import CSVWriter
from mcps.storage.json_writer import JSONWriter
from mcps.storage.sqlite_writer import SQLiteWriter
from shared.contracts.mcp_error import ErrorCode, MCPError
from shared.models.product import Product
from shared.models.validation_result import ValidationResult
from shared.utils.config import Config, get_config
from shared.utils.logging import get_logger

logger = get_logger(__name__)


class WriteResult(BaseModel):
    schema_version: str = Field(default="1.0", frozen=True)
    success: bool
    formats_written: list[str] = Field(default_factory=list)
    error: MCPError | None = None


class StorageMCP:
    """Orchestration layer mapping data records to active format drivers."""

    def __init__(self, config: Config | None = None) -> None:
        self.config = config or get_config()
        self.csv_writer = CSVWriter(self.config)
        self.json_writer = JSONWriter(self.config)
        self.sqlite_writer = SQLiteWriter(self.config)

    async def write(
        self,
        product: Product,
        validation: ValidationResult,
    ) -> WriteResult:
        """Write product data to all enabled output formats in parallel.

        Args:
            product: Product model instance.
            validation: ValidationResult matching the product.

        Returns:
            WriteResult indicating success or errors.
        """
        formats = self.config.output.formats
        tasks = []
        formats_written = []

        logger.info("Executing storage write", formats=formats, product_title=product.title)

        if "csv" in formats:
            tasks.append(self.csv_writer.write(product, validation))
            formats_written.append("csv")
        if "json" in formats:
            tasks.append(self.json_writer.write(product, validation))
            formats_written.append("json")
        if "sqlite" in formats:
            tasks.append(self.sqlite_writer.write(product, validation))
            formats_written.append("sqlite")

        try:
            # Execute all writes concurrently
            await asyncio.gather(*tasks)
            return WriteResult(success=True, formats_written=formats_written)
        except Exception as e:
            logger.error("Failed executing storage write tasks", error=str(e))
            return WriteResult(
                success=False,
                error=MCPError(
                    code=ErrorCode.STORAGE_WRITE_ERROR,
                    message=f"Storage driver failure: {str(e)}",
                ),
            )

    async def flush(self) -> None:
        """Flush buffers to disks."""
        await asyncio.gather(
            self.csv_writer.flush(),
            self.json_writer.flush(),
            self.sqlite_writer.flush(),
        )

    async def close(self) -> None:
        """Cleanly close all writers."""
        await asyncio.gather(
            self.csv_writer.close(),
            self.json_writer.close(),
            self.sqlite_writer.close(),
        )
