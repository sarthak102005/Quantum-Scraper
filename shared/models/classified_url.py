"""
shared/models/classified_url.py

ClassifiedURL — a URL that has been assigned a page type with a confidence score.
Produced by Classification MCP; consumed by Crawler MCP and ADK Planner.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


PageType = Literal[
    "PRODUCT",
    "CATEGORY",
    "PRODUCT_FAMILY",
    "NAVIGATION_HUB",
    "SERVICE",
    "SUPPORT",
    "DOCUMENTATION",
    "BLOG",
    "NEWS",
    "LANDING_PAGE",
    "DEALER",
    "SEARCH_RESULTS",
    "ACCOUNT",
    "UNKNOWN",
]

VALID_PAGE_TYPES: set[str] = {
    "PRODUCT",
    "CATEGORY",
    "PRODUCT_FAMILY",
    "NAVIGATION_HUB",
    "SERVICE",
    "SUPPORT",
    "DOCUMENTATION",
    "BLOG",
    "NEWS",
    "LANDING_PAGE",
    "DEALER",
    "SEARCH_RESULTS",
    "ACCOUNT",
    "UNKNOWN",
}


def normalize_page_type(value: str) -> PageType:
    """Safely coerce any returned page type string to a valid PageType."""
    cleaned = (value or "UNKNOWN").upper().strip()
    if cleaned in VALID_PAGE_TYPES:
        return cleaned  # type: ignore[return-value]
    
    # Backwards compatibility mappings for lowercase legacy names:
    compat_map = {
        "PRODUCT": "PRODUCT",
        "CATEGORY": "CATEGORY",
        "NAVIGATION_HUB": "NAVIGATION_HUB",
        "NAVIGATION": "NAVIGATION_HUB",
        "HUB": "NAVIGATION_HUB",
        "SUBCATEGORY": "CATEGORY",
        "PAGINATION": "CATEGORY",
        "HOME": "LANDING_PAGE",
        "UNKNOWN": "UNKNOWN"
    }
    return compat_map.get(cleaned, "UNKNOWN")  # type: ignore[return-value]



class ClassifiedURL(BaseModel):
    """A URL with its assigned page type and classification confidence."""

    schema_version: str = Field(default="1.0", frozen=True)

    url: str
    page_type: PageType = "UNKNOWN"
    
    @field_validator("page_type", mode="before")
    @classmethod
    def validate_page_type(cls, v: Any) -> str:
        if isinstance(v, str):
            return normalize_page_type(v)
        return v
        
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    # Signals that contributed to this classification
    signals_fired: list[str] = Field(default_factory=list)

    # Crawl priority: higher = crawled sooner
    # product=3, category=2, pagination=1, unknown/home=0
    priority: int = Field(default=0, ge=0)

    # Nav position: lower value = appeared earlier (more left) in the navbar.
    # Used as a tiebreaker so left-nav product sections are visited before
    # right-nav utility sections (shop, racing, experience, etc.).
    # Default 9999 means "no nav position known" (e.g. came from sitemap only).
    nav_position: int = Field(default=9999, ge=0)

    depth: int = Field(default=0, ge=0)
    parent_url: str | None = None
    classified_at: datetime = Field(default_factory=datetime.utcnow)

    def __lt__(self, other: "ClassifiedURL") -> bool:
        """Priority queue comparison — higher priority first."""
        return self.priority > other.priority
