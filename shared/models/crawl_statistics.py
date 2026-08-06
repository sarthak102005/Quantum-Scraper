"""
shared/models/crawl_statistics.py

CrawlStatistics — real-time and summary metrics for a crawl session.
Used by Knowledge MCP to update WebsiteProfile after each crawl.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class CrawlStatistics(BaseModel):
    """Metrics snapshot for a single crawl task."""

    schema_version: str = Field(default="1.0", frozen=True)

    task_id: str
    domain: str

    # URL counts
    total_discovered: int = 0
    total_fetched: int = 0
    total_products_extracted: int = 0
    total_products_passed: int = 0
    total_products_failed: int = 0
    total_skipped: int = 0      # non-product pages intentionally skipped
    total_errors: int = 0

    # Fetch method breakdown
    http_fetches: int = 0
    playwright_fetches: int = 0
    cache_hits: int = 0

    # Timing
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None

    # Latency (milliseconds)
    average_latency_ms: float = 0.0
    total_latency_ms: float = 0.0

    # Anti-bot signals observed
    rate_limit_events: int = 0
    forbidden_events: int = 0
    challenge_events: int = 0

    @property
    def success_rate(self) -> float:
        """Fraction of fetched pages that produced a PASS product."""
        if self.total_fetched == 0:
            return 0.0
        return self.total_products_passed / self.total_fetched

    @property
    def browser_fetch_ratio(self) -> float:
        """Fraction of fetches that required Playwright."""
        total = self.http_fetches + self.playwright_fetches
        if total == 0:
            return 0.0
        return self.playwright_fetches / total

    @property
    def elapsed_seconds(self) -> float | None:
        if self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None

    def record_latency(self, latency_ms: float) -> None:
        """Update the rolling average latency."""
        self.total_latency_ms += latency_ms
        if self.total_fetched > 0:
            self.average_latency_ms = self.total_latency_ms / self.total_fetched
