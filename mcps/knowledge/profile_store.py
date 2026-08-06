"""
mcps/knowledge/profile_store.py

ProfileStore — handles SQLite persistence for WebsiteProfiles, versioned
selectors, and historical crawl metrics.
"""

from __future__ import annotations

import json
from pathlib import Path

import aiosqlite

from shared.models.crawl_statistics import CrawlStatistics
from shared.models.website_profile import WebsiteProfile
from shared.utils.logging import get_logger

logger = get_logger(__name__)


class ProfileStore:
    """SQLite data manager storing profile documents and counts."""

    def __init__(self, db_path: str) -> None:
        self.db_path = Path(db_path)
        self._conn: aiosqlite.Connection | None = None

    async def init(self) -> None:
        """Initialize the DB connection and prepare schemas."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.db_path)

        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS website_profiles (
                domain TEXT PRIMARY KEY,
                profile_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)

        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS selector_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                domain TEXT NOT NULL,
                version TEXT NOT NULL,
                selectors JSON NOT NULL,
                source TEXT DEFAULT 'auto',
                success_count INTEGER DEFAULT 0,
                failure_count INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                UNIQUE(domain, version)
            );
        """)

        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS crawl_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                domain TEXT NOT NULL,
                task_id TEXT NOT NULL,
                stats_json TEXT NOT NULL,
                recorded_at TEXT NOT NULL
            );
        """)

        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS classification_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                domain TEXT NOT NULL,
                url TEXT NOT NULL,
                confidence REAL NOT NULL,
                is_product INTEGER NOT NULL,
                signals_json TEXT NOT NULL,
                recorded_at TEXT NOT NULL
            );
        """)

        await self._conn.commit()
        logger.info("Knowledge SQLite store initialized")

    async def get_profile(self, domain: str) -> WebsiteProfile | None:
        """Fetch profile from database."""
        assert self._conn, "Database connection not initialized"
        async with self._conn.execute(
            "SELECT profile_json FROM website_profiles WHERE domain = ?", (domain,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return WebsiteProfile.model_validate_json(row[0])
        return None

    async def save_profile(self, profile: WebsiteProfile) -> None:
        """Upsert profile metadata into SQLite store."""
        assert self._conn, "Database connection not initialized"
        profile_json = profile.model_dump_json()
        now_str = profile.updated_at.isoformat()
        
        await self._conn.execute(
            """
            INSERT OR REPLACE INTO website_profiles (domain, profile_json, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (profile.domain, profile_json, profile.created_at.isoformat(), now_str),
        )
        await self._conn.commit()

    async def save_selector_version(
        self,
        domain: str,
        version: str,
        selectors: dict,
        source: str = "auto",
    ) -> None:
        """Save a new selector version rules configuration."""
        assert self._conn, "Database connection not initialized"
        import datetime
        now_str = datetime.datetime.utcnow().isoformat()
        
        await self._conn.execute(
            """
            INSERT OR IGNORE INTO selector_versions (domain, version, selectors, source, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (domain, version, json.dumps(selectors), source, now_str),
        )
        await self._conn.commit()

    async def increment_success(self, domain: str, version: str) -> None:
        """Increment extraction success metrics counter."""
        assert self._conn, "Database connection not initialized"
        await self._conn.execute(
            """
            UPDATE selector_versions
            SET success_count = success_count + 1
            WHERE domain = ? AND version = ?
            """,
            (domain, version),
        )
        await self._conn.commit()

    async def increment_failure(self, domain: str, version: str) -> None:
        """Increment failure metrics counter."""
        assert self._conn, "Database connection not initialized"
        await self._conn.execute(
            """
            UPDATE selector_versions
            SET failure_count = failure_count + 1
            WHERE domain = ? AND version = ?
            """,
            (domain, version),
        )
        await self._conn.commit()

    async def get_version_stats(self, domain: str, version: str) -> tuple[int, int]:
        """Fetch success and failure count metrics for a selector version."""
        assert self._conn, "Database connection not initialized"
        async with self._conn.execute(
            "SELECT success_count, failure_count FROM selector_versions WHERE domain = ? AND version = ?",
            (domain, version),
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return row[0], row[1]
        return 0, 0

    async def record_crawl_metrics(self, domain: str, task_id: str, stats: CrawlStatistics) -> None:
        """Persist session statistics record."""
        assert self._conn, "Database connection not initialized"
        import datetime
        now_str = datetime.datetime.utcnow().isoformat()
        
        await self._conn.execute(
            """
            INSERT INTO crawl_metrics (domain, task_id, stats_json, recorded_at)
            VALUES (?, ?, ?, ?)
            """,
            (domain, task_id, stats.model_dump_json(), now_str),
        )
        await self._conn.commit()

    async def record_classification(
        self,
        domain: str,
        url: str,
        confidence: float,
        is_product: bool,
        signals: list[str],
    ) -> None:
        """Record details of a single URL classification in the database."""
        assert self._conn, "Database connection not initialized"
        import datetime
        now_str = datetime.datetime.utcnow().isoformat()
        
        await self._conn.execute(
            """
            INSERT INTO classification_history (domain, url, confidence, is_product, signals_json, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (domain, url, confidence, 1 if is_product else 0, json.dumps(signals), now_str),
        )
        await self._conn.commit()

    async def get_classification_stats(self, domain: str) -> dict[str, Any]:
        """Fetch historical statistics about classifications for this domain."""
        assert self._conn, "Database connection not initialized"
        
        stats = {
            "avg_confidence_products": 0.0,
            "avg_confidence_non_products": 0.0,
            "top_positive_signals": [],
            "top_false_positives": []
        }
        
        # 1. Average confidence for products
        async with self._conn.execute(
            "SELECT AVG(confidence) FROM classification_history WHERE domain = ? AND is_product = 1", (domain,)
        ) as cursor:
            row = await cursor.fetchone()
            if row and row[0] is not None:
                stats["avg_confidence_products"] = float(row[0])

        # 2. Average confidence for non-products
        async with self._conn.execute(
            "SELECT AVG(confidence) FROM classification_history WHERE domain = ? AND is_product = 0", (domain,)
        ) as cursor:
            row = await cursor.fetchone()
            if row and row[0] is not None:
                stats["avg_confidence_non_products"] = float(row[0])

        return stats

    async def close(self) -> None:
        """Disconnect database connection context."""
        if self._conn:
            await self._conn.close()
            self._conn = None
            logger.info("Knowledge store connection closed")
stream = None
