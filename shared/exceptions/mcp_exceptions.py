"""
shared/exceptions/mcp_exceptions.py

Internal exceptions for use WITHIN a single MCP only.
These must NEVER cross MCP boundaries.
Convert to MCPError before returning from any public MCP method.
"""

from __future__ import annotations

from shared.contracts.mcp_error import ErrorCode


class MCPInternalError(Exception):
    """Base class for all internal MCP exceptions."""

    def __init__(self, message: str, code: ErrorCode = ErrorCode.INTERNAL_ERROR) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class FetchError(MCPInternalError):
    """Raised when an HTTP fetch fails."""

    def __init__(self, message: str, code: ErrorCode = ErrorCode.CONNECTION_ERROR) -> None:
        super().__init__(message, code)


class RateLimitError(MCPInternalError):
    """Raised when a rate limit (429) is encountered."""

    def __init__(self, retry_after: float | None = None) -> None:
        super().__init__("Rate limit encountered", ErrorCode.RATE_LIMITED)
        self.retry_after = retry_after


class ParseError(MCPInternalError):
    """Raised when HTML/XML/JSON parsing fails."""

    def __init__(self, message: str) -> None:
        super().__init__(message, ErrorCode.PARSE_ERROR)


class ExtractionError(MCPInternalError):
    """Raised when extraction produces no usable output."""

    def __init__(self, message: str) -> None:
        super().__init__(message, ErrorCode.EXTRACTION_FAILED)


class StorageError(MCPInternalError):
    """Raised when a write to storage fails."""

    def __init__(self, message: str) -> None:
        super().__init__(message, ErrorCode.STORAGE_WRITE_ERROR)


class ProfileNotFoundError(MCPInternalError):
    """Raised when a WebsiteProfile cannot be found in the knowledge store."""

    def __init__(self, domain: str) -> None:
        super().__init__(f"No profile found for domain: {domain}", ErrorCode.PROFILE_NOT_FOUND)
