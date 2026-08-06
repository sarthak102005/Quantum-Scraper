"""
shared/utils/url_utils.py

URL normalisation, deduplication, and validation utilities.
Used by Discovery MCP and Crawler MCP to guarantee clean URL sets.
"""

from __future__ import annotations

import re
from urllib.parse import (
    SplitResult,
    urljoin,
    urlsplit,
    urlunsplit,
)


def normalise(url: str, base: str | None = None) -> str | None:
    """Normalise a URL to a canonical form.

    Steps applied:
    1. Resolve relative URLs against ``base`` if provided.
    2. Lowercase the scheme and host.
    3. Remove the URL fragment (#...).
    4. Strip trailing slash inconsistencies (keep path as-is, but collapse ///).
    5. Remove default ports (80 for http, 443 for https).
    6. Sort query parameters for deterministic comparison.

    Args:
        url: The URL string to normalise.
        base: Optional base URL to resolve relative paths against.

    Returns:
        Normalised URL string, or None if the URL is invalid.
    """
    if not url or not url.strip():
        return None

    url = url.strip()

    # Resolve relative URLs
    if base:
        url = urljoin(base, url)

    try:
        parts: SplitResult = urlsplit(url)
    except ValueError:
        return None

    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        return None

    netloc = parts.netloc.lower()

    # Strip default ports
    if ":" in netloc:
        host, port_str = netloc.rsplit(":", 1)
        if port_str.isdigit():
            port = int(port_str)
            if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
                netloc = host

    # Normalise path — collapse multiple slashes
    path = re.sub(r"/+", "/", parts.path) or "/"

    # Sort query string for deterministic keys
    query = parts.query
    if query:
        pairs = sorted(query.split("&"))
        query = "&".join(pairs)

    # Drop fragment entirely
    normalised = urlunsplit((scheme, netloc, path, query, ""))
    return normalised


def deduplicate(urls: list[str], base: str | None = None) -> list[str]:
    """Normalise and deduplicate a list of URLs, preserving order.

    Args:
        urls: Raw URL strings (may contain duplicates or relative paths).
        base: Optional base URL for resolving relative paths.

    Returns:
        List of unique normalised URLs in first-seen order.
    """
    seen: set[str] = set()
    result: list[str] = []

    for raw in urls:
        normalised = normalise(raw, base=base)
        if normalised and normalised not in seen:
            seen.add(normalised)
            result.append(normalised)

    return result


def is_valid_url(url: str) -> bool:
    """Return True if ``url`` is a valid absolute http/https URL.

    Args:
        url: URL string to validate.

    Returns:
        True if the URL is syntactically valid and uses http or https.
    """
    if not url or not isinstance(url, str):
        return False

    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return False

    return (
        parts.scheme in ("http", "https")
        and bool(parts.netloc)
        and bool(parts.netloc.split(":")[0])  # non-empty host
    )


def extract_domain(url: str) -> str | None:
    """Extract the registered domain (host) from a URL.

    Args:
        url: An absolute URL string.

    Returns:
        The hostname (without port), or None if the URL is invalid.
    """
    try:
        parts = urlsplit(url.strip())
        host = parts.netloc.lower()
        # Strip port
        return host.split(":")[0] if host else None
    except ValueError:
        return None


def same_domain(url1: str, url2: str) -> bool:
    """Return True if both URLs share the same host.

    Args:
        url1: First URL.
        url2: Second URL.

    Returns:
        True if both URLs have identical hosts.
    """
    return extract_domain(url1) == extract_domain(url2)
