"""
shared/contracts/mcp_error.py

Universal error response model. Every MCP method returns this on failure.
Exceptions must NEVER cross MCP boundaries — wrap them in MCPError instead.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class ErrorCode(str, Enum):
    # Network / fetch errors
    NOT_FOUND = "NOT_FOUND"
    FORBIDDEN = "FORBIDDEN"
    RATE_LIMITED = "RATE_LIMITED"
    TIMEOUT = "TIMEOUT"
    CONNECTION_ERROR = "CONNECTION_ERROR"
    RETRIES_EXHAUSTED = "RETRIES_EXHAUSTED"

    # Parsing errors
    PARSE_ERROR = "PARSE_ERROR"
    INVALID_HTML = "INVALID_HTML"

    # Extraction errors
    EXTRACTION_FAILED = "EXTRACTION_FAILED"
    LLM_OUTPUT_INVALID = "LLM_OUTPUT_INVALID"

    # Validation errors
    VALIDATION_FAILED = "VALIDATION_FAILED"
    DUPLICATE_SKU = "DUPLICATE_SKU"

    # Storage errors
    STORAGE_WRITE_ERROR = "STORAGE_WRITE_ERROR"

    # Config / internal errors
    CONFIG_ERROR = "CONFIG_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"

    # Knowledge MCP errors
    PROFILE_NOT_FOUND = "PROFILE_NOT_FOUND"
    DB_ERROR = "DB_ERROR"


class MCPError(BaseModel):
    """Universal error envelope returned by all MCP methods on failure."""

    schema_version: str = Field(default="1.0", frozen=True)
    code: ErrorCode
    message: str
    retryable: bool = False
    context: dict[str, object] = Field(default_factory=dict)
