"""
mcps/extraction/selector_extractor.py

Selector Extractor — extracts product fields from HTML using CSS and XPath
selectors mapped inside the WebsiteProfile.
"""

from __future__ import annotations

import re
from typing import Literal
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from lxml import etree

from shared.models.extraction_result import ExtractionResult, FieldConfidence
from shared.models.product import Product
from shared.models.website_profile import SelectorSet
from shared.utils.logging import get_logger

logger = get_logger(__name__)


async def extract(
    html: str,
    selector_set: SelectorSet | None,
    method: Literal["css", "xpath"],
    source_url: str,
) -> ExtractionResult:
    """Extract product properties from HTML source using CSS selectors or XPaths.

    Args:
        html: HTML source.
        selector_set: Versioned selector rules dictionary.
        method: Parsing selector type ('css' or 'xpath').
        source_url: Page URL.

    Returns:
        ExtractionResult containing mapped attributes.
    """
    logger.info("Running Selector Extraction Stage", method=method, url=source_url)

    if not selector_set or not selector_set.selectors:
        logger.warning("No selector sets provided; skipping stage", method=method)
        return ExtractionResult(success=False, confidence=0.0, method=method, source_url=source_url)

    extracted_fields: dict[str, str] = {}
    field_confs: list[FieldConfidence] = []

    # Method weightings
    weight = 0.85 if method == "css" else 0.80

    if method == "css":
        soup = BeautifulSoup(html, "html.parser")
        for field, rules in selector_set.selectors.items():
            css_rule = rules.get("css")
            if not css_rule:
                continue

            element = soup.select_one(css_rule)
            if element:
                if element.name == "meta" and element.has_attr("content"):
                    val = element["content"]
                else:
                    val = element.get_text()
                # Apply transform
                val = _apply_transform(val, rules.get("transform"))
                if val:
                    extracted_fields[field] = val
                    field_confs.append(FieldConfidence(field_name=field, score=weight, method=method))

    else:  # xpath method
        try:
            parser = etree.HTMLParser()
            tree = etree.fromstring(html, parser)

            for field, rules in selector_set.selectors.items():
                xpath_rule = rules.get("xpath")
                if not xpath_rule:
                    continue

                elements = tree.xpath(xpath_rule)
                if elements:
                    # Resolve element text node or attribute value
                    first = elements[0]
                    if isinstance(first, etree._Element):
                        val = first.text or "".join(first.itertext())
                    else:
                        val = str(first)

                    val = _apply_transform(val, rules.get("transform"))
                    if val:
                        extracted_fields[field] = val
                        field_confs.append(FieldConfidence(field_name=field, score=weight, method=method))

        except Exception as e:
            logger.error("lxml XPath engine failed to parse HTML", error=str(e))
            return ExtractionResult(success=False, confidence=0.0, method=method, source_url=source_url)

    # Resolve required product properties
    title = extracted_fields.get("title")
    price = _parse_float(extracted_fields.get("price"))
    currency = extracted_fields.get("currency")
    availability = extracted_fields.get("availability") or "in_stock"
    brand = extracted_fields.get("brand")
    sku = extracted_fields.get("sku")
    description = extracted_fields.get("description")

    # Parse any specs if present
    specifications = {}
    for k, v in extracted_fields.items():
        if k.startswith("spec_") or k.startswith("specification_"):
            clean_k = k.replace("spec_", "").replace("specification_", "").replace("_", " ").title()
            specifications[clean_k] = v

    if not title:
        return ExtractionResult(success=False, confidence=0.0, method=method, source_url=source_url)

    product = Product(
        source_url=source_url,
        domain=urlsplit(source_url).netloc,
        title=title,
        price=price,
        currency=currency,
        brand=brand,
        sku=sku,
        description=description,
        availability=availability,
        specifications=specifications,
        extraction_method=method,
    )

    # Spec-compliant confidence calculation: (fields_found / total_required_fields) * method_weight
    required_fields = [title, price, currency, availability, brand]
    fields_found = sum(1 for f in required_fields if f is not None)
    confidence = (fields_found / 5.0) * weight

    return ExtractionResult(
        success=True,
        product=product,
        confidence=confidence,
        method=method,
        field_confidences=field_confs,
        source_url=source_url,
    )


def _apply_transform(val: str | None, transform: str | None) -> str | None:
    """Helper to sanitize output strings based on rules."""
    if not val:
        return None
    val = val.strip()
    if not transform:
        return val

    if transform == "strip":
        return val
    elif transform == "to_float":
        clean = re.sub(r"[^\d\.]", "", val)
        return clean if clean else None
    elif transform == "to_int":
        clean = re.sub(r"[^\d]", "", val)
        return clean if clean else None
    return val


def _parse_float(val: str | None) -> float | None:
    """Helper converting string to float."""
    if not val:
        return None
    try:
        return float(val)
    except ValueError:
        return None
