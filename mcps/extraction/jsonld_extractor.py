"""
mcps/extraction/jsonld_extractor.py

JSON-LD Extractor — extracts product structured data schemas from HTML script blocks
and maps standard schemas to Product models.
"""

from __future__ import annotations

import json
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from shared.models.extraction_result import ExtractionResult, FieldConfidence
from shared.models.product import Product
from shared.models.product_variant import ProductVariant
from shared.utils.logging import get_logger

logger = get_logger(__name__)


async def extract(html: str, source_url: str) -> ExtractionResult:
    """Parse JSON-LD script blocks and OpenGraph tags to extract product data.

    Args:
        html: Full HTML page source.
        source_url: Target URL of the page.

    Returns:
        ExtractionResult containing populated Product model if matches are found.
    """
    logger.info("Running JSON-LD Extraction Stage", url=source_url)
    soup = BeautifulSoup(html, "html.parser")

    product_data: dict[str, object] = {}
    variant_list: list[ProductVariant] = []

    # 1. Parse JSON-LD blocks
    json_ld_blocks = soup.find_all("script", type="application/ld+json")
    for block in json_ld_blocks:
        try:
            data = json.loads(block.string or "")
            # Support list wrapper or object
            items = data if isinstance(data, list) else [data]

            for item in items:
                # Resolve "@graph" nests
                graph_items = item.get("@graph", [item]) if isinstance(item, dict) else [item]

                for g_item in graph_items:
                    if not isinstance(g_item, dict):
                        continue

                    obj_type = g_item.get("@type", "")
                    if isinstance(obj_type, list):
                        is_product = any("product" in str(t).lower() for t in obj_type)
                    else:
                        is_product = "product" in str(obj_type).lower()

                    if is_product:
                        product_data.update(g_item)

        except Exception as e:
            logger.warning("Failed to parse JSON-LD block", error=str(e))

    # 2. Extract OpenGraph as fallback mappings
    og_data = {}
    for meta in soup.find_all("meta", property=True):
        prop = meta["property"].lower()
        if prop.startswith("og:") or prop.startswith("product:"):
            og_data[prop] = meta.get("content", "")

    # Mappings from JSON-LD or OpenGraph
    title = product_data.get("name") or og_data.get("og:title")
    description = product_data.get("description") or og_data.get("og:description")

    brand = None
    brand_node = product_data.get("brand")
    if isinstance(brand_node, dict):
        brand = brand_node.get("name")
    elif isinstance(brand_node, str):
        brand = brand_node
    brand = brand or og_data.get("product:brand")

    sku = product_data.get("sku") or product_data.get("mpn")
    if isinstance(sku, list) and sku:
        sku = str(sku[0])
    elif sku:
        sku = str(sku)

    # Images
    images = []
    img_node = product_data.get("image")
    if isinstance(img_node, list):
        images.extend([str(img) for img in img_node])
    elif isinstance(img_node, str):
        images.append(img_node)
    elif isinstance(img_node, dict):
        images.append(img_node.get("url", ""))

    if not images and "og:image" in og_data:
        images.append(og_data["og:image"])

    # Price and Currency resolving
    price = None
    currency = None
    availability = None

    offers = product_data.get("offers")
    if isinstance(offers, dict):
        # Could be single Offer or AggregateOffer
        offer_type = offers.get("@type", "")

        if "AggregateOffer" in str(offer_type):
            price_val = offers.get("lowPrice") or offers.get("highPrice") or offers.get("price")
            price = _parse_float(price_val)
            currency = offers.get("priceCurrency")
        else:
            price = _parse_float(offers.get("price"))
            currency = offers.get("priceCurrency")

        avail_str = offers.get("availability")
        if avail_str:
            if "InStock" in str(avail_str):
                availability = "in_stock"
            elif "OutOfStock" in str(avail_str):
                availability = "out_of_stock"

    # OpenGraph fallbacks
    if price is None:
        price = _parse_float(og_data.get("og:price:amount") or og_data.get("product:price:amount"))
    if currency is None:
        currency = og_data.get("og:price:currency") or og_data.get("product:price:currency")
    if availability is None:
        og_avail = og_data.get("og:availability") or og_data.get("product:availability")
        if og_avail:
            availability = "in_stock" if "instock" in str(og_avail).lower() else "out_of_stock"

    # Check mapping success
    if not (title or price or currency):
        return ExtractionResult(success=False, confidence=0.0, method="jsonld", source_url=source_url)

    # Construct clean Product instance
    product = Product(
        source_url=source_url,
        domain=urlsplit(source_url).netloc,
        title=title,
        price=price,
        currency=currency,
        brand=brand,
        sku=sku,
        description=description,
        availability=availability or "in_stock",
        image_urls=images,
        extraction_method="jsonld",
    )

    # Spec-compliant confidence calculation: 0.95 if all required fields found, 0.7 if partial
    required_present = all([title, price is not None, currency, brand, availability])
    confidence = 0.95 if required_present else 0.70

    # Build per-field breakdown
    field_conf = [
        FieldConfidence(field_name="title", score=0.95 if title else 0.0, method="jsonld"),
        FieldConfidence(field_name="price", score=0.95 if price else 0.0, method="jsonld"),
        FieldConfidence(field_name="currency", score=0.95 if currency else 0.0, method="jsonld"),
        FieldConfidence(field_name="brand", score=0.95 if brand else 0.0, method="jsonld"),
    ]

    return ExtractionResult(
        success=True,
        product=product,
        confidence=confidence,
        method="jsonld",
        field_confidences=field_conf,
        source_url=source_url,
    )


def _parse_float(val: object) -> float | None:
    """Helper to convert objects safely to float."""
    if val is None:
        return None
    try:
        clean = re.sub(r"[^\d\.]", "", str(val))
        return float(clean)
    except ValueError:
        return None
