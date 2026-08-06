"""
shared/models/website_profile.py

WebsiteProfile — the central learning artefact.
Persisted by Knowledge MCP. Read by every MCP to avoid repeated discovery.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class SelectorSet(BaseModel):
    """A versioned set of CSS/XPath selectors for a specific domain."""

    version: str
    selectors: dict[str, dict[str, str | None]] = Field(
        default_factory=dict,
        description="field_name -> {css, xpath, transform}",
    )
    source: Literal["auto", "manual"] = "auto"
    success_count: int = 0
    failure_count: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)


class WebsiteProfile(BaseModel):
    """Persisted knowledge about a website, used to improve future crawls."""

    schema_version: str = Field(default="1.0", frozen=True)

    domain: str
    seed_url: str

    # Fetch strategy learned from prior crawls
    preferred_fetch_method: Literal["requests", "playwright"] = "requests"
    anti_bot_level: Literal["none", "low", "medium", "high"] = "none"
    requires_javascript: bool = False

    # Robots.txt directives
    robots_disallow: list[str] = Field(default_factory=list)
    robots_allow: list[str] = Field(default_factory=list)
    crawl_delay_ms: int | None = None

    # URL patterns learned from discovery
    product_url_patterns: list[str] = Field(default_factory=list)
    category_url_patterns: list[str] = Field(default_factory=list)
    sitemap_urls: list[str] = Field(default_factory=list)
    navigation_markdown: str | None = None

    # Selector knowledge
    selector_version: str = "v1"
    selector_sets: list[SelectorSet] = Field(default_factory=list)

    # Performance metrics (rolling averages)
    average_latency_ms: float = 0.0
    recommended_concurrency: int = 3
    success_rate: float = 0.0

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    last_crawled_at: datetime | None = None

    # DOM fingerprint (used to detect site redesigns)
    dom_signature: str | None = None

    def get_active_selector_set(self) -> SelectorSet | None:
        """Return the selector set matching the current selector_version."""
        for ss in self.selector_sets:
            if ss.version == self.selector_version:
                return ss
        return None
