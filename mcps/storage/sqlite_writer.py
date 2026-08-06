"""
mcps/storage/sqlite_writer.py

SQLite Writer — streams product entries to SQLite databases asynchronously
using aiosqlite pools.
"""

from __future__ import annotations

import json
from pathlib import Path

import asyncio
import aiosqlite

from shared.models.product import Product
from shared.models.validation_result import ValidationResult
from shared.utils.config import Config, get_config
from shared.utils.logging import get_logger

logger = get_logger(__name__)


class SQLiteWriter:
    """Inserts records dynamically into structured SQLite database tables."""

    def __init__(self, config: Config | None = None) -> None:
        self.config = config or get_config()
        self.lock = asyncio.Lock()
        self.db_path = Path(self.config.output.directory) / "products.db"
        self._conn: aiosqlite.Connection | None = None

    async def _get_conn(self) -> aiosqlite.Connection:
        """Lazily initialize table schemas and connection pool."""
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = await aiosqlite.connect(self.db_path)
            
            # Create schema table
            await self._conn.execute("""
                CREATE TABLE IF NOT EXISTS products (
                    product_id TEXT PRIMARY KEY,
                    source_url TEXT,
                    domain TEXT,
                    extracted_at TEXT,
                    title TEXT,
                    price REAL,
                    currency TEXT,
                    brand TEXT,
                    sku TEXT,
                    availability TEXT,
                    description TEXT,
                    category TEXT,
                    rating REAL,
                    review_count INTEGER,
                    image_urls TEXT,
                    variants TEXT,
                    specifications TEXT,
                    extraction_method TEXT,
                    validation_verdict TEXT
                )
            """)
            await self._conn.commit()
        return self._conn

    async def write(self, product: Product, validation: ValidationResult) -> None:
        """Execute async INSERT statement on write event."""
        async with self.lock:
            conn = await self._get_conn()
            
            # Flatten lists/dicts
            images_str = ",".join(product.image_urls)
            variants_str = json.dumps([v.model_dump() for v in product.variants])
            specs_str = json.dumps(product.specifications)

            try:
                await conn.execute(
                    """
                    INSERT OR REPLACE INTO products (
                        product_id, source_url, domain, extracted_at, title,
                        price, currency, brand, sku, availability, description,
                        category, rating, review_count, image_urls, variants,
                        specifications, extraction_method, validation_verdict
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        product.product_id,
                        product.source_url,
                        product.domain,
                        product.extracted_at.isoformat(),
                        product.title,
                        product.price,
                        product.currency,
                        product.brand,
                        product.sku,
                        product.availability,
                        product.description,
                        product.category,
                        product.rating,
                        product.review_count,
                        images_str,
                        variants_str,
                        specs_str,
                        product.extraction_method,
                        validation.verdict,
                    ),
                )
                await conn.commit()
            except Exception as e:
                logger.error("Failed to insert product record into SQLite", error=str(e), db=str(self.db_path))

    async def flush(self) -> None:
        """Commit outstanding SQLite transactions."""
        if self._conn:
            await self._conn.commit()

    async def close(self) -> None:
        """Close SQLite DB connection."""
        async with self.lock:
            if self._conn:
                await self._conn.close()
                self._conn = None
                logger.info("SQLite storage database pool closed")
