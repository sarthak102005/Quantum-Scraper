"""
shared/models/product_variant.py

ProductVariant — size/colour/SKU variant of a product.
Embedded in the Product model.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ProductVariant(BaseModel):
    """A single size/colour/configuration variant of a product."""

    schema_version: str = Field(default="1.0", frozen=True)

    sku: str | None = None
    name: str | None = None            # e.g. "Red / XL"
    price: float | None = None
    currency: str | None = None
    availability: str | None = None
    image_url: str | None = None
    attributes: dict[str, str] = Field(
        default_factory=dict,
        description="Free-form variant attributes, e.g. {'color': 'red', 'size': 'XL'}",
    )
