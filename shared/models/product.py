"""
shared/models/product.py

Product — the core data entity extracted from product pages.
Fields marked 'required' must be present for a ValidationResult of PASS.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from pydantic import BaseModel, Field

from shared.models.product_variant import ProductVariant


class Product(BaseModel):
    """Structured product data extracted from a product page."""

    schema_version: str = Field(default="1.0", frozen=True)

    # Internal tracking
    product_id: str = Field(default_factory=lambda: str(uuid4()))
    source_url: str
    domain: str
    crawl_task_id: str | None = None
    extracted_at: datetime = Field(default_factory=datetime.utcnow)

    # ── Required fields (must be present for PASS validation) ──
    title: str | None = None             # required
    price: float | None = None           # required
    currency: str | None = None          # required (ISO-4217, e.g. "USD")
    availability: str | None = None      # required ("in_stock", "out_of_stock", etc.)
    brand: str | None = None             # required

    # ── Optional fields ──
    sku: str | None = None
    description: str | None = None
    category: str | None = None
    breadcrumbs: list[str] = Field(default_factory=list)
    rating: float | None = None
    review_count: int | None = None
    image_urls: list[str] = Field(default_factory=list)
    variants: list[ProductVariant] = Field(default_factory=list)
    specifications: dict[str, str] = Field(default_factory=dict)
    raw_price_text: str | None = None

    # Extraction metadata
    extraction_method: str | None = None   # "jsonld", "css", "xpath", "semantic", "llm"
    extraction_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
