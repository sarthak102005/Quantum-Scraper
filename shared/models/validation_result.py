"""
shared/models/validation_result.py

ValidationResult — output of the Validation MCP.
Contains the verdict (PASS/WARN/FAIL), errors, warnings, and retry recommendation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


Verdict = Literal["PASS", "WARN", "FAIL"]


class ValidationResult(BaseModel):
    """Result of validating an ExtractionResult."""

    schema_version: str = Field(default="1.0", frozen=True)

    verdict: Verdict
    quality_score: float = Field(default=0.0, ge=0.0, le=1.0)

    # Field-level errors (FAIL-triggering)
    errors: list[str] = Field(default_factory=list)

    # Non-blocking warnings
    warnings: list[str] = Field(default_factory=list)

    # Whether the Planner should retry extraction with a different method
    retry_recommended: bool = False
    retry_reason: str | None = None

    # Whether this product was detected as a duplicate
    is_duplicate: bool = False
    duplicate_of: str | None = None   # product_id of the original

    validated_at: datetime = Field(default_factory=datetime.utcnow)
    source_url: str = ""

    @property
    def passed(self) -> bool:
        """Convenience: True when verdict is PASS."""
        return self.verdict == "PASS"

    @property
    def failed(self) -> bool:
        """Convenience: True when verdict is FAIL."""
        return self.verdict == "FAIL"
