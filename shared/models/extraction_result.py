"""
shared/models/extraction_result.py

ExtractionResult — output of the Extraction MCP pipeline.
Carries the extracted Product, confidence, method used, and any warnings.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from shared.contracts.mcp_error import MCPError
from shared.models.product import Product


ExtractionMethod = Literal["jsonld", "css", "xpath", "semantic", "llm", "none"]


class FieldConfidence(BaseModel):
    """Per-field confidence score from the extraction pipeline."""

    field_name: str
    score: float = Field(ge=0.0, le=1.0)
    method: ExtractionMethod = "none"


class ExtractionResult(BaseModel):
    """Output of the Extraction MCP's 5-stage pipeline."""

    schema_version: str = Field(default="1.0", frozen=True)

    success: bool
    product: Product | None = None

    # Overall confidence (0.0–1.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    # Which pipeline stage produced the final result
    method: ExtractionMethod = "none"

    # Per-field breakdown
    field_confidences: list[FieldConfidence] = Field(default_factory=list)

    # Non-fatal issues encountered during extraction
    warnings: list[str] = Field(default_factory=list)

    # Set only on complete failure
    error: MCPError | None = None

    extracted_at: datetime = Field(default_factory=datetime.utcnow)
    source_url: str = ""
