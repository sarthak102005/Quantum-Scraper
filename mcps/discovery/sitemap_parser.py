"""
mcps/discovery/sitemap_parser.py

Recursively fetches and parses XML sitemaps, extracting all page URLs.
Handles compressed sitemaps (.gz) and sitemap indexes.

Key design: scope_segments (derived from the seed URL's path prefix) are passed
down so that child sitemap entries whose filenames cannot contain in-scope content
are skipped BEFORE any network requests are made. This is the only correct fix for
multi-locale sitemap indexes that list 100+ country-specific child sitemaps.
"""

from __future__ import annotations

import asyncio
import gzip
import io
import re
from urllib.parse import urljoin, urlsplit

import aiohttp
from bs4 import BeautifulSoup

from shared.utils.logging import get_logger
from shared.utils.url_utils import deduplicate

logger = get_logger(__name__)

# Sitemap filenames containing these patterns contain media assets, not crawlable pages.
_MEDIA_SITEMAP_PATTERNS = ("pdpimage", "image", "video", "videos", "media", "assets")

# Non-catalog path segments that are noise for product discovery.
_NON_CATALOG_SEGMENTS = (
    "/locations/", "/blog/", "/news/", "/events/", "/careers/",
    "/about/", "/contact/", "/support/", "/store-locator/",
    "/find-a-dealer/", "/press/", "/corporate/", "/legal/", "/privacy/",
)


def _extract_locale_hints(path_prefix: str) -> list[str]:
    """
    Derive short locale/country hint tokens from a path prefix.

    Examples:
        /us/       -> ["us", "en-us", "en_us"]
        /en-gb/    -> ["gb", "en-gb", "en_gb"]
        /de/       -> ["de", "de-de", "de_de"]
        /          -> []   (no filtering, accept all)

    These tokens are used to match against child sitemap filenames so we only
    fetch the one(s) that can contain in-scope content.
    """
    if not path_prefix or path_prefix.strip("/") == "":
        return []

    # Take the first meaningful path segment (e.g. "us" from "/us/products/")
    segments = [s for s in path_prefix.strip("/").split("/") if s]
    if not segments:
        return []

    first = segments[0].lower()
    hints = [first]

    # If it looks like a language-country code (e.g. "en-gb"), also add the country part
    m = re.match(r"^([a-z]{2})[-_]([a-z]{2})$", first)
    if m:
        hints.append(m.group(2))  # country only
    else:
        # Single code like "us" — also add "en-us" variant
        hints.append(f"en-{first}")
        hints.append(f"en_{first}")

    return hints


def _child_sitemap_is_relevant(child_url: str, locale_hints: list[str]) -> bool:
    """
    Return True if a child sitemap URL is plausibly relevant to the target locale.

    Strategy:
      1. Always accept if no hints (whole-domain scope or no path prefix).
      2. Skip media sitemaps unconditionally.
      3. If the filename contains locale-like tokens (e.g. "hbd-us-en-us"),
         accept only if at least one hint matches a token in the filename.
      4. If the filename has no locale tokens at all (generic names like
         "sitemap.xml", "products.xml"), always accept.
    """
    filename = child_url.lower().rsplit("/", 1)[-1]

    # Always skip media/asset sitemaps
    if any(p in filename for p in _MEDIA_SITEMAP_PATTERNS):
        return False

    # No scope hints → accept everything
    if not locale_hints:
        return True

    # Split filename on non-alphanumeric chars to get tokens
    tokens = set(re.split(r"[^a-z0-9]+", filename))

    # Remove file extension tokens
    tokens.discard("xml")
    tokens.discard("gz")
    tokens.discard("")

    # Heuristic: if the filename contains 3+ locale-looking tokens (e.g. "hbd", "us", "en", "us")
    # then it's a locale-specific sitemap → filter strictly.
    # Otherwise (e.g. "sitemap.xml", "products.xml") → accept unconditionally.
    locale_token_pattern = re.compile(r"^[a-z]{2,4}$")
    locale_tokens = [t for t in tokens if locale_token_pattern.match(t)]

    if len(locale_tokens) < 2:
        # Generic sitemap name — accept for all locales
        return True

    # Locale-specific sitemap → require at least one hint to appear in the tokens
    hints_set = set(h.replace("-", "").replace("_", "") for h in locale_hints)
    tokens_plain = set(t.replace("-", "").replace("_", "") for t in tokens)
    return bool(hints_set & tokens_plain)


async def fetch_all_urls(
    sitemap_url: str,
    session: aiohttp.ClientSession,
    max_depth: int = 5,
    _current_depth: int = 1,
    locale_hints: list[str] | None = None,
) -> list[str]:
    """Recursively fetch and parse a sitemap index or leaf sitemap.

    Args:
        sitemap_url:    Absolute URL of the sitemap XML file.
        session:        Active ClientSession to use.
        max_depth:      Maximum recursion depth for nested sitemaps.
        _current_depth: Internal counter (do not set externally).
        locale_hints:   Short locale tokens derived from the seed path prefix
                        (e.g. ["us", "en-us"]). Child sitemaps whose filenames
                        don't match any hint are skipped without a network
                        request. Pass [] or None to disable filtering.

    Returns:
        Deduplicated list of page URLs found within scope.
    """
    if _current_depth > max_depth:
        logger.warning("Reached max sitemap recursion depth", url=sitemap_url)
        return []

    logger.info("Fetching sitemap", url=sitemap_url, depth=_current_depth)
    try:
        async with session.get(sitemap_url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            if resp.status != 200:
                logger.warning("Sitemap fetch failed", status=resp.status, url=sitemap_url)
                return []

            raw_data = await resp.read()

            # Decompress if gzipped
            if sitemap_url.lower().endswith(".gz") or resp.content_type in (
                "application/x-gzip", "application/gzip"
            ):
                try:
                    with gzip.GzipFile(fileobj=io.BytesIO(raw_data)) as f:
                        xml_content = f.read()
                except Exception as e:
                    logger.error("Decompression failed for gzipped sitemap", error=str(e), url=sitemap_url)
                    return []
            else:
                xml_content = raw_data

    except Exception as e:
        logger.error("Error fetching sitemap", error=str(e), url=sitemap_url)
        return []

    try:
        soup = BeautifulSoup(xml_content, "lxml-xml")
    except Exception as e:
        logger.error("Failed to parse sitemap XML", error=str(e), url=sitemap_url)
        return []

    urls: list[str] = []

    # ── Sitemap Index (<sitemapindex>) ──────────────────────────────────────
    sitemap_tags = soup.find_all("sitemap")
    if sitemap_tags:
        all_child_locs = [
            sm.find("loc").text.strip()
            for sm in sitemap_tags
            if sm.find("loc") and sm.find("loc").text
        ]

        # Filter child sitemaps BEFORE making any network requests.
        # This is the key optimisation: for multi-locale sites, only fetch the
        # child sitemap(s) whose filename matches the target locale.
        hints = locale_hints or []
        relevant_locs = [
            loc for loc in all_child_locs
            if _child_sitemap_is_relevant(loc, hints)
        ]

        skipped = len(all_child_locs) - len(relevant_locs)
        logger.info(
            "Sitemap index filtered",
            total_children=len(all_child_locs),
            fetching=len(relevant_locs),
            skipped=skipped,
        )

        if not relevant_locs:
            logger.warning(
                "All child sitemaps were filtered out; falling back to first 5 generic ones",
                hints=hints,
            )
            # Safety fallback: if filtering is too aggressive, take the first few
            relevant_locs = all_child_locs[:5]

        # Fetch the relevant child sitemaps concurrently (max 10 at a time)
        semaphore = asyncio.Semaphore(10)

        async def fetch_child(loc: str) -> list[str]:
            async with semaphore:
                return await fetch_all_urls(
                    loc,
                    session,
                    max_depth=max_depth,
                    _current_depth=_current_depth + 1,
                    locale_hints=locale_hints,  # propagate hints recursively
                )

        results = await asyncio.gather(
            *[fetch_child(loc) for loc in relevant_locs],
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, list):
                urls.extend(result)
            elif isinstance(result, Exception):
                logger.warning("Failed to fetch child sitemap", error=str(result))

        return deduplicate(urls)

    # ── Standard URL Set (<urlset>) ─────────────────────────────────────────
    for tag in soup.find_all("url"):
        loc = tag.find("loc")
        if loc and loc.text:
            page_url = loc.text.strip()
            # Drop known non-catalog paths early
            path = urlsplit(page_url).path.lower()
            if any(seg in path for seg in _NON_CATALOG_SEGMENTS):
                continue
            urls.append(page_url)

    logger.info("Extracted URLs from sitemap", count=len(urls), url=sitemap_url)
    return deduplicate(urls)
