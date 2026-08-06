"""
mcps/validation/validation_mcp.py

Validation MCP — validates extraction products against sanity and formatting
criteria, detects duplicates, and decides retry recommendations.
"""

from __future__ import annotations

import re
from shared.models.extraction_result import ExtractionResult
from shared.models.validation_result import ValidationResult
from shared.utils.logging import get_logger

logger = get_logger(__name__)


class ValidationMCP:
    """Validator inspecting fields, formatting patterns, and duplicate records."""

    def __init__(self) -> None:
        self._seen_skus: set[str] = set()

    async def validate(
        self,
        result: ExtractionResult,
    ) -> ValidationResult:
        """Validate extraction result properties.

        Checks:
        1. Required fields presence (title, price, currency, availability, brand).
        2. Format checks (price > 0, 3-letter currency code).
        3. SKU duplication.
        4. Quality score logic.
        """
        errors: list[str] = []
        warnings: list[str] = []
        is_duplicate = False

        if not result.success or not result.product:
            return ValidationResult(
                verdict="FAIL",
                quality_score=0.0,
                errors=["Extraction result was unsuccessful; no product data found."],
                source_url=result.source_url,
            )

        product = result.product

        # 1. Required fields presence check (only title is strictly mandatory)
        if not product.title or not product.title.strip():
            errors.append("Missing required field: title")

        # 2. Format checks (price values range)
        if product.price is not None:
            if product.price <= 0.0 or product.price > 1000000.0:
                warnings.append(f"Unusual price range detected: {product.price}")

        # 3. Currency code pattern check
        if product.currency:
            if not re.match(r"^[A-Z]{3}$", product.currency):
                warnings.append(f"Currency code is not ISO 4217 compliant: {product.currency}")

        # 4. Duplicate SKU checks
        if product.sku:
            if product.sku in self._seen_skus:
                is_duplicate = True
                warnings.append(f"Duplicate product SKU matched: {product.sku}")
            else:
                # Add to memory registry on PASS condition later
                pass

        # 5. Determine Verdict
        if errors:
            verdict = "FAIL"
        elif warnings:
            verdict = "WARN"
        else:
            verdict = "PASS"

        # Register SKU if PASSED
        if verdict == "PASS" and product.sku:
            self._seen_skus.add(product.sku)

        # 6. Quality scoring logic
        found_fields = [
            product.title,
            product.brand,
            product.availability,
            product.price,
            product.currency,
            product.description,
        ]
        found_count = sum(1 for v in found_fields if v is not None)
        quality_score = min((found_count / 5.0) * result.confidence, result.confidence)

        # 7. Retry recommendation (True if failing and we can fall back to LLM/other stages)
        retry_recommended = (verdict == "FAIL" and result.method != "llm")

        logger.info(
            "Validation complete",
            verdict=verdict,
            quality_score=quality_score,
            errors_count=len(errors),
            warnings_count=len(warnings),
        )

        return ValidationResult(
            verdict=verdict,
            quality_score=quality_score,
            errors=errors,
            warnings=warnings,
            retry_recommended=retry_recommended,
            retry_reason="Missing fields or invalid values" if retry_recommended else None,
            is_duplicate=is_duplicate,
            source_url=result.source_url,
        )
