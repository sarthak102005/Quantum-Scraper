"""
mcps/extraction/llm_extractor.py

LLM Extractor — extracts product structured attributes using primary/fallback
generative models when rules-based stages fail.
"""

from __future__ import annotations

import json
import re
from urllib.parse import urlsplit

from pydantic import ValidationError

from shared.utils.llm_utils import llm_with_fallback
from shared.models.extraction_result import ExtractionResult, FieldConfidence
from shared.models.product import Product
from shared.utils.config import Config, get_config
from shared.utils.logging import get_logger

logger = get_logger(__name__)


async def extract(html: str, source_url: str, config: Config | None = None) -> ExtractionResult:
    """Invokes fallback LLM chain to extract attributes from raw text snippets.

    Args:
        html: HTML source.
        source_url: Page URL.
        config: Config instance.

    Returns:
        ExtractionResult containing populated Product or failure envelope.
    """
    cfg = config or get_config()

    if not cfg.llm.extraction_fallback_enabled:
        logger.info("LLM extraction fallback is disabled; skipping stage", url=source_url)
        return ExtractionResult(success=False, confidence=0.0, method="llm", source_url=source_url)

    logger.info("Running LLM Extraction Stage (Fallback Mode)", url=source_url)

    # Clean HTML code to feed text to LLM
    text_content = _clean_html_for_llm(html)
    # Truncate content to avoid token overflow
    truncated_content = text_content[:8000]

    prompt = f"""
You are an expert data extraction assistant. Extract product details from the web page source text provided below.
Return ONLY a valid JSON object matching the JSON schema below. Do not include markdown codeblocks or conversational text.

Required fields to locate:
- title: Name of product (string)
- price: Price of the product (float number)
- currency: ISO 4217 currency code (e.g. USD, EUR)
- availability: One of ["in_stock", "out_of_stock"]
- brand: Name of brand/manufacturer (string)

Optional fields to locate:
- sku: Product code (string)
- description: Brief description (string)
- category: Breadcrumb or Category name (string)

Output JSON Format example:
{{
  "title": "Wireless Headphones Pro",
  "price": 149.99,
  "currency": "USD",
  "availability": "in_stock",
  "brand": "SoundMax",
  "sku": "WHP-001",
  "description": "Premium noise-cancelling headphones."
}}

Web page content snippet:
-----------------------------
{truncated_content}
-----------------------------
"""

    try:
        # Run prompt through fallback chain (Gemini -> Groq -> OpenRouter)
        resp_text = await llm_with_fallback(prompt, cfg)

        # Parse JSON output from LLM block
        product_dict = _extract_json_block(resp_text)
        if not product_dict:
            logger.error("LLM did not return a parsable JSON block", response=resp_text)
            return ExtractionResult(success=False, confidence=0.0, method="llm", source_url=source_url)

        # Validate with Pydantic
        product = Product(
            source_url=source_url,
            domain=urlsplit(source_url).netloc,
            title=product_dict.get("title"),
            price=product_dict.get("price"),
            currency=product_dict.get("currency"),
            brand=product_dict.get("brand"),
            sku=product_dict.get("sku"),
            description=product_dict.get("description"),
            availability=product_dict.get("availability") or "in_stock",
            extraction_method="llm",
        )

        field_confs = [
            FieldConfidence(field_name=k, score=0.90, method="llm")
            for k, v in product_dict.items() if v is not None
        ]

        logger.info("Successfully extracted product via LLM", title=product.title, price=product.price)
        return ExtractionResult(
            success=True,
            product=product,
            confidence=0.90,
            method="llm",
            field_confidences=field_confs,
            source_url=source_url,
        )

    except ValidationError as val_err:
        logger.error("LLM properties failed Product validation schema", error=str(val_err))
        return ExtractionResult(success=False, confidence=0.0, method="llm", source_url=source_url)
    except Exception as e:
        logger.error("LLM extraction stage crashed completely", error=str(e))
        return ExtractionResult(success=False, confidence=0.0, method="llm", source_url=source_url)


def _clean_html_for_llm(html: str) -> str:
    """Helper to remove scripts, styles, and collapse white spaces."""
    # Simple tag strip to extract layout text strings
    text = re.sub(r"<(script|style|svg|noscript)[^>]*>([\s\S]*?)<\/\1>", " ", html, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_json_block(text: str) -> dict | None:
    """Helper extracting dict out of Markdown blocks."""
    # Find block starting with { and ending with }
    match = re.search(r"(\{[\s\S]*?\})", text)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except Exception:
        return None
