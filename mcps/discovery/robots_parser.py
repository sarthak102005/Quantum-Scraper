"""
mcps/discovery/robots_parser.py

Fetches and parses robots.txt from a website using aiohttp.
Extracts allowed paths, disallowed paths, crawl delay, and sitemap URLs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import aiohttp

from shared.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class RobotsData:
    """Parsed robots.txt guidelines."""

    disallow_paths: list[str] = field(default_factory=list)
    allow_paths: list[str] = field(default_factory=list)
    sitemap_urls: list[str] = field(default_factory=list)
    crawl_delay_seconds: float | None = None


async def fetch_and_parse(domain: str, session: aiohttp.ClientSession) -> RobotsData:
    """Fetch robots.txt for domain and extract directives matching User-agent: *.

    Args:
        domain: Domain of the target website (e.g., 'example.com').
        session: Active ClientSession to make the HTTP request.

    Returns:
        RobotsData instance with parsed instructions.
    """
    url = f"https://{domain}/robots.txt"
    data = RobotsData()

    logger.info("Fetching robots.txt", url=url)
    try:
        async with session.get(url, timeout=10) as resp:
            if resp.status != 200:
                logger.warning("robots.txt not found or unavailable", status=resp.status, url=url)
                return data
            content = await resp.text()
    except Exception as e:
        logger.error("Failed to fetch robots.txt", error=str(e), url=url)
        return data

    # Parse content
    current_ua_applies = False

    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # Extract directive and value
        match = re.match(r"^([^:]+)\s*:\s*(.+)$", line)
        if not match:
            continue

        directive = match.group(1).strip().lower()
        value = match.group(2).strip()

        if directive == "sitemap":
            data.sitemap_urls.append(value)
            continue

        if directive == "user-agent":
            # Match wildcards or general user-agents
            current_ua_applies = (value == "*")
            continue

        if current_ua_applies:
            if directive == "disallow":
                if value:
                    data.disallow_paths.append(value)
            elif directive == "allow":
                if value:
                    data.allow_paths.append(value)
            elif directive == "crawl-delay":
                try:
                    data.crawl_delay_seconds = float(value)
                except ValueError:
                    pass

    logger.info(
        "Parsed robots.txt directives",
        disallow_count=len(data.disallow_paths),
        allow_count=len(data.allow_paths),
        sitemaps_found=len(data.sitemap_urls),
        crawl_delay=data.crawl_delay_seconds,
    )
    return data
