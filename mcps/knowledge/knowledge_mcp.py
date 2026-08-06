"""
mcps/knowledge/knowledge_mcp.py

Knowledge MCP — analyzes prior metrics to recommend optimal concurrency limits,
preferred fetch methods, selector versions, and skip discovery indicators.
"""

from __future__ import annotations

import datetime
from typing import Literal
from pydantic import BaseModel, Field

from mcps.knowledge.profile_store import ProfileStore
from shared.models.crawl_statistics import CrawlStatistics
from shared.models.website_profile import WebsiteProfile
from shared.utils.logging import get_logger

logger = get_logger(__name__)


class ProfileRecommendations(BaseModel):
    schema_version: str = Field(default="1.0", frozen=True)
    preferred_fetch_method: Literal["requests", "playwright"] = "requests"
    recommended_concurrency: int = 3
    selector_version: str = "v1"
    skip_discovery: bool = False
    rollback_selector_version: bool = False
    recommended_selector_version: str | None = None
    notes: list[str] = Field(default_factory=list)


class KnowledgeMCP:
    """The self-learning analytics manager."""

    def __init__(self, db_path: str) -> None:
        self.store = ProfileStore(db_path)

    async def init(self) -> None:
        """Startup DB tables."""
        await self.store.init()

    async def get_profile(self, domain: str) -> WebsiteProfile | None:
        """Fetch profile from database."""
        try:
            return await self.store.get_profile(domain)
        except Exception as e:
            logger.error("Failed to read profile from database", error=str(e), domain=domain)
            return None

    async def save_profile(self, profile: WebsiteProfile) -> None:
        """Upsert profile data."""
        try:
            profile.updated_at = datetime.datetime.utcnow()
            await self.store.save_profile(profile)
        except Exception as e:
            logger.error("Failed to save profile into database", error=str(e), domain=profile.domain)

    async def record_extraction_success(
        self,
        domain: str,
        selector_version: str,
        method: str,
    ) -> None:
        """Increment selector version success statistics."""
        try:
            await self.store.increment_success(domain, selector_version)
        except Exception as e:
            logger.error("Failed writing extraction success metrics", error=str(e))

    async def record_extraction_failure(
        self,
        domain: str,
        selector_version: str,
    ) -> None:
        """Increment selector version failure statistics."""
        try:
            await self.store.increment_failure(domain, selector_version)
        except Exception as e:
            logger.error("Failed writing extraction failure metrics", error=str(e))

    async def get_recommendations(self, domain: str) -> ProfileRecommendations:
        """Calculates optimal scraping config parameters for a target domain.

        Checks:
        1. Preferred fetch method.
        2. Rollback selectors check (if failures > success).
        3. Skip discovery indicator.
        """
        logger.info("Evaluating domain recommendations", domain=domain)
        profile = await self.get_profile(domain)
        
        if not profile:
            return ProfileRecommendations(notes=["Fresh domain target; no historical profile found."])

        notes = []
        preferred_fetch_method = profile.preferred_fetch_method
        recommended_concurrency = profile.recommended_concurrency
        selector_version = profile.selector_version
        rollback = False

        # Check selector health status
        success, failures = await self.store.get_version_stats(domain, selector_version)
        if failures > success and (success + failures) > 5:
            rollback = True
            notes.append(f"Selector version {selector_version} failure rate is high; rollback suggested.")

        # Determine skip discovery if profile is recently updated and url patterns exist
        skip_discovery = False
        ttl_delta = datetime.datetime.utcnow() - profile.updated_at
        if ttl_delta.days < 7 and (profile.product_url_patterns or profile.sitemap_urls):
            skip_discovery = True
            notes.append("Skipping discovery stage; using cached sitemaps and patterns.")

        return ProfileRecommendations(
            preferred_fetch_method=preferred_fetch_method,
            recommended_concurrency=recommended_concurrency,
            selector_version=selector_version,
            skip_discovery=skip_discovery,
            rollback_selector_version=rollback,
            notes=notes,
        )

    async def update_from_crawl(
        self,
        stats: CrawlStatistics,
        profile: WebsiteProfile,
    ) -> None:
        """Aggregates metrics from finished crawl to tune target profile parameters."""
        logger.info("Updating website profile with crawl statistics", domain=profile.domain)

        # 1. Update rolling average latency
        if profile.average_latency_ms > 0:
            profile.average_latency_ms = (profile.average_latency_ms + stats.average_latency_ms) / 2.0
        else:
            profile.average_latency_ms = stats.average_latency_ms

        # 2. Adjust concurrency limits based on error/rate limit counts
        # If rate limited, decrement limit, if smooth run, increment limit
        if stats.rate_limit_events > 0 or stats.forbidden_events > 0:
            profile.recommended_concurrency = max(profile.recommended_concurrency - 1, 1)
        elif stats.success_rate > 0.90:
            profile.recommended_concurrency = min(profile.recommended_concurrency + 1, 10)

        # 3. Update preferred fetch method based on Playwright ratio
        if stats.browser_fetch_ratio > 0.70:
            profile.preferred_fetch_method = "playwright"
        else:
            profile.preferred_fetch_method = "requests"

        # 4. Anti-bot level
        total_bot_walls = stats.rate_limit_events + stats.forbidden_events + stats.challenge_events
        if total_bot_walls == 0:
            profile.anti_bot_level = "none"
        elif total_bot_walls <= 2:
            profile.anti_bot_level = "low"
        elif total_bot_walls <= 5:
            profile.anti_bot_level = "medium"
        else:
            profile.anti_bot_level = "high"

        profile.last_crawled_at = datetime.datetime.utcnow()
        profile.updated_at = datetime.datetime.utcnow()

        # Update statistics in DB
        await self.save_profile(profile)
        await self.store.record_crawl_metrics(profile.domain, stats.task_id, stats)
        logger.info("Website profile updated successfully")

    async def record_classification(
        self,
        domain: str,
        url: str,
        confidence: float,
        is_product: bool,
        signals: list[str],
    ) -> None:
        """Record a single URL classification trial into database."""
        try:
            await self.store.record_classification(domain, url, confidence, is_product, signals)
        except Exception as e:
            logger.error("Failed recording classification details", error=str(e))

    async def get_classification_stats(self, domain: str) -> dict[str, Any]:
        """Query historical statistics about domain classifications."""
        try:
            return await self.store.get_classification_stats(domain)
        except Exception as e:
            logger.error("Failed querying classification history stats", error=str(e))
            return {
                "avg_confidence_products": 0.0,
                "avg_confidence_non_products": 0.0,
                "top_positive_signals": [],
                "top_false_positives": []
            }

    async def close(self) -> None:
        """Disposes store driver connection."""
        await self.store.close()
