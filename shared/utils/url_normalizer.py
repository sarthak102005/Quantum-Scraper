"""
shared/utils/url_normalizer.py

URL Normalizer utility to prevent duplicate crawling and standardize URLs.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def normalize_url(url: str, canonical_url: str | None = None) -> str:
    """Normalize a URL by removing tracking params, sorting queries, and standardizing.

    Args:
        url: The absolute target URL string.
        canonical_url: Optional canonical URL string extracted from page head.

    Returns:
        Standardized URL string.
    """
    target = canonical_url if canonical_url else url
    if not target:
        return ""

    try:
        parts = urlsplit(target)
        scheme = parts.scheme.lower()
        netloc = parts.netloc.lower()
        
        # Remove trailing slash and resolve empty path
        path = parts.path
        if path.endswith("/"):
            path = path.rstrip("/")
        if not path:
            path = "/"

        # Parse query params and remove tracking parameters
        query_params = parse_qsl(parts.query)
        clean_params = []
        tracking_prefixes = ("utm_", "fbclid", "gclid", "affiliate", "ref")
        for key, value in query_params:
            if not key.lower().startswith(tracking_prefixes):
                clean_params.append((key, value))

        # Sort parameters to ensure unique signature
        clean_params.sort(key=lambda x: x[0])

        new_query = urlencode(clean_params) if clean_params else ""

        # Remove fragment/hash parameters
        return urlunsplit((scheme, netloc, path, new_query, ""))
    except Exception:
        # Fallback to simple strip if parsing fails
        return target.strip()
