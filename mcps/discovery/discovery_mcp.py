"""
mcps/discovery/discovery_mcp.py

Discovery MCP — analyzes a target website from a seed URL to construct
the initial WebsiteProfile and gather candidate URLs using robots, sitemaps,
and Playwright navigation menu parser.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

import aiohttp
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

from mcps.discovery.robots_parser import fetch_and_parse
from mcps.discovery.sitemap_parser import fetch_all_urls, _extract_locale_hints
from mcps.playwright.playwright_mcp import BrowserInstructions
from shared.models.crawl_task import CrawlTask
from shared.models.website_profile import WebsiteProfile
from shared.utils.config import Config
from shared.utils.logging import get_logger
from shared.utils.url_utils import deduplicate, normalise
from shared.utils.scope_manager import ScopeManager

logger = get_logger(__name__)


class DiscoveryResult(BaseModel):
    """Output envelope for the Discovery MCP."""

    schema_version: str = Field(default="1.0", frozen=True)
    profile: WebsiteProfile
    urls: list[str]
    # Maps URL -> nav DOM position (0-indexed, lower = more left in navbar).
    # Only populated for URLs that appeared in the rendered navigation menu.
    nav_url_positions: dict[str, int] = Field(default_factory=dict)
    metadata: dict[str, object] = Field(default_factory=dict)


class DiscoveryMCP:
    """Discovers targets and initializes learning profile for a domain."""

    def __init__(self, config: Config, playwright_mcp: Any | None = None) -> None:
        self.config = config
        self.playwright_mcp = playwright_mcp

    async def discover(self, task: CrawlTask) -> DiscoveryResult:
        """Constructs WebsiteProfile and gathers initial URL set.

        Args:
            task: The target CrawlTask detailing seed URL and constraints.

        Returns:
            DiscoveryResult containing initial WebsiteProfile and discovered URLs.
        """
        domain = task.domain
        seed_url = task.seed_url

        # Instantiate ScopeManager
        policy = self.config.crawl_scope.policy
        scope_manager = ScopeManager(seed_url, policy=policy)

        # Derive locale hints from the seed path prefix for scope-aware sitemap filtering.
        # e.g. seed=/us/ -> hints=["us","en-us"]; seed=/ -> hints=[] (no filtering)
        locale_hints = _extract_locale_hints(scope_manager.boundary.allowed_prefix)

        # Initialise profile
        profile = WebsiteProfile(domain=domain, seed_url=seed_url)
        urls: list[str] = []

        logger.info("Starting discovery with scope policy", domain=domain, seed_url=seed_url, policy=policy)

        async with aiohttp.ClientSession() as session:
            # 1. Parse robots.txt
            robots_data = await fetch_and_parse(domain, session)
            profile.robots_disallow = robots_data.disallow_paths
            profile.robots_allow = robots_data.allow_paths
            if robots_data.crawl_delay_seconds:
                profile.crawl_delay_ms = int(robots_data.crawl_delay_seconds * 1000)

            # Sitemaps list
            sitemaps = robots_data.sitemap_urls or [f"https://{domain}/sitemap.xml"]
            profile.sitemap_urls = sitemaps

            # 2. Parse sitemaps recursively (validating host domain only, bypass locale prefix check)
            sitemaps_parsed_count = 0
            sitemap_urls_count = 0
            for sm_url in sitemaps:
                try:
                    parts = urlsplit(sm_url)
                    netloc = parts.netloc.lower()
                    clean_netloc = netloc[4:] if netloc.startswith("www.") else netloc
                    if clean_netloc != scope_manager.boundary.allowed_host and not clean_netloc.endswith("." + scope_manager.boundary.allowed_host):
                        logger.warning("Bypassing sitemap outside allowed host", sitemap_url=sm_url, allowed_host=scope_manager.boundary.allowed_host)
                        continue
                except Exception as ex:
                    logger.warning("Failed to parse sitemap URL host", sitemap_url=sm_url, error=str(ex))
                    continue

                try:
                    sitemaps_parsed_count += 1
                    # Pass locale_hints so sitemap_parser skips irrelevant country
                    # sitemaps BEFORE making network requests (the root cause fix).
                    sm_urls = await fetch_all_urls(
                        sm_url, session, locale_hints=locale_hints
                    )
                    sitemap_urls_count += len(sm_urls)
                    # sm_urls are already scope-filtered by sitemap_parser; just
                    # apply the path prefix guard as a final safety net.
                    for target_url in sm_urls:
                        try:
                            target_path = urlsplit(target_url).path.lower()
                            allowed_prefix = scope_manager.boundary.allowed_prefix.lower()
                            if scope_manager.boundary.boundary_type in ("PATH_PREFIX", "CUSTOM_PATH_PREFIX"):
                                if not target_path.startswith(allowed_prefix.rstrip("/") + "/") and target_path != allowed_prefix.rstrip("/"):
                                    continue
                        except Exception:
                            pass
                        urls.append(target_url)
                except Exception as e:
                    logger.debug("Sitemap parse error", url=sm_url, error=str(e))

            # 3. Always pull home page to extract navigation hierarchy & handle dynamic JS rendering
            html_content = ""
            homepage_urls_count = 0
            if self.playwright_mcp:
                logger.info("Rendering seed URL via Playwright for navigation hierarchy", seed_url=seed_url)
                render_res = await self.playwright_mcp.render(
                    seed_url,
                    BrowserInstructions(timeout_ms=20000, scroll_to_bottom=False)
                )
                if render_res.success and render_res.html:
                    html_content = render_res.html

            # Fallback to standard HTTP GET if Playwright not available or failed
            if not html_content:
                logger.info("Fetching seed URL via standard HTTP client", seed_url=seed_url)
                try:
                    async with session.get(seed_url, timeout=15) as resp:
                        if resp.status == 200:
                            html_content = await resp.text()
                except Exception as e:
                    logger.error("Failed to fetch seed URL homepage", error=str(e))

            # Parse navigation elements if homepage HTML was fetched
            if html_content:
                soup = BeautifulSoup(html_content, "html.parser")

                # 3a. Extract structured Markdown of primary navigation links
                profile.navigation_markdown = self._extract_navigation_markdown(soup, seed_url)

                # 3b. Add all page links to candidate list if sitemaps were empty/outdated
                homepage_anchors = soup.find_all("a", href=True)
                homepage_urls_count = len(homepage_anchors)
                if not urls:
                    logger.info("Sitemaps yielded no URLs; fallback to homepage links extraction")
                    for a in homepage_anchors:
                        norm = normalise(a["href"], base=seed_url)
                        if norm:
                            urls.append(norm)

        # Filter discovered URLs to ensure they match target domain and scope boundary
        raw_combined_count = len(urls)
        
        # 1. Normalization & Deduplication of raw combined URLs
        normalized_urls = []
        for url in urls:
            norm = scope_manager.normalize(url)
            if norm:
                normalized_urls.append(norm)
                
        deduplicated_raw_count = len(set(normalized_urls))
        raw_duplicates_removed = raw_combined_count - deduplicated_raw_count

        domain_urls = []
        for url in urls:
            decision = scope_manager.validate(
                url,
                source_page="discovery_filter",
                discovery_method="discovery_post_filter",
            )
            # Accept both newly validated or already validated duplicate-tracked accepts
            if decision.decision in ("ACCEPT", "REJECT_DUPLICATE"):
                domain_urls.append(decision.normalized_url)

        # Final deduplicate
        final_urls = deduplicate(domain_urls)

        # 4. Generate URL pattern regex heuristics
        self._learn_url_patterns(final_urls, profile)

        # 5. Build nav position map from the navigation markdown
        nav_url_positions: dict[str, int] = {}
        if profile.navigation_markdown:
            import re as _re
            nav_links = _re.findall(r"\(https?://[^)]+\)", profile.navigation_markdown)
            for pos, link in enumerate(nav_links):
                nav_url = link.strip("()")
                if nav_url not in nav_url_positions:
                    nav_url_positions[nav_url] = pos

        # Detailed Discovery Pipeline Diagnostics Logger Block
        logger.info(
            "\n"
            "====================================================\n"
            "               DISCOVERY PIPELINE DIAGNOSTICS\n"
            "====================================================\n"
            f"robots.txt discovered:        {'Yes' if robots_data.disallow_paths or robots_data.allow_paths else 'No'}\n"
            f"Sitemap references found:     {len(sitemaps)}\n"
            f"Individual sitemaps parsed:   {sitemaps_parsed_count}\n"
            f"URLs extracted from sitemaps: {sitemap_urls_count}\n"
            f"URLs extracted from homepage: {homepage_urls_count}\n"
            f"Combined URLs:                {raw_combined_count}\n"
            f"Normalized URLs:              {len(normalized_urls)}\n"
            f"Duplicates removed:           {raw_duplicates_removed}\n"
            f"URLs after Scope Manager:     {len(domain_urls)}\n"
            f"URLs entering classification: {len(final_urls)}\n"
            "===================================================="
        )

        logger.info(
            "Discovery complete",
            total_discovered=len(final_urls),
            product_patterns_found=len(profile.product_url_patterns),
            category_patterns_found=len(profile.category_url_patterns),
            has_nav_markdown=profile.navigation_markdown is not None,
            nav_positions_tracked=len(nav_url_positions),
        )

        return DiscoveryResult(
            profile=profile,
            urls=final_urls,
            nav_url_positions=nav_url_positions,
            metadata={"robots_crawl_delay": profile.crawl_delay_ms},
        )

    def _extract_navigation_markdown(self, soup: BeautifulSoup, base_url: str) -> str:
        """Find primary header, footer, sidebar, and breadcrumbs navigation structures and convert to a structured Markdown outline.

        Target tags: <nav>, <header>, <footer>, sidebar layouts, and divs with nav-related class names.
        """
        nav_elements = []

        # Priority selectors
        selectors = [
            "nav", "header", "footer", ".footer", "#footer", ".sidebar", "#sidebar",
            "div[class*='nav']", "div[class*='menu']", "div[id*='menu']", "div[class*='header']"
        ]

        for selector in selectors:
            found = soup.select(selector)
            if found:
                nav_elements.extend(found)

        # Check for breadcrumbs
        breadcrumbs = soup.select(".breadcrumbs, .breadcrumb, [class*='breadcrumb'], [id*='breadcrumb']")
        if breadcrumbs:
            nav_elements.extend(breadcrumbs)

        # If no explicit nav structures found, fallback to top page container
        if not nav_elements:
            nav_elements = [soup]

        markdown_lines = ["# Navigation Menu Layout", ""]
        seen_links = set()

        for container in nav_elements:
            # Build hierarchal paths
            for li in container.find_all("li"):
                # Get the link
                a = li.find("a", href=True)
                if a and a["href"] not in seen_links:
                    norm_url = normalise(a["href"], base=base_url)
                    if not norm_url:
                        continue
                    seen_links.add(a["href"])

                    # Compute hierarchy path up to parent elements
                    path_titles = []
                    for parent in li.parents:
                        if parent == container:
                            break
                        # Find preceding header/label or list item text
                        if parent.name in ('li', 'ul', 'div'):
                            label = ""
                            # Look for headings in parent div/section
                            h_elem = parent.find(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
                            if h_elem:
                                label = h_elem.get_text(strip=True)
                            if not label:
                                # Look for sibling text or label
                                label = parent.get_text(strip=True).split('\n')[0].strip()[:30]
                            if label and label not in path_titles:
                                path_titles.insert(0, label)

                    # Construct hierarchical line: Header 1 > Header 2 > ... > Link
                    link_text = a.get_text(strip=True) or "Link"
                    path_titles.append(link_text)
                    hierarchy_path = " > ".join([p for p in path_titles if p])
                    markdown_lines.append(f"- [{hierarchy_path}]({norm_url})")

        # If list parsing yielded nothing, grab any anchor with parent layout details
        if len(seen_links) < 5:
            for container in nav_elements:
                for a in container.find_all("a", href=True):
                    if a["href"] not in seen_links:
                        link_text = a.get_text(strip=True)
                        norm_url = normalise(a["href"], base=base_url)
                        if norm_url and link_text:
                            seen_links.add(a["href"])
                            markdown_lines.append(f"- [{link_text}]({norm_url})")

        return "\n".join(markdown_lines)

    def _learn_url_patterns(self, urls: list[str], profile: WebsiteProfile) -> None:
        """Analyze URL paths to learn regex patterns for products and categories."""
        product_regexes = [
            r"/product/.*",
            r"/p/.*",
            r"/item/.*",
            r"/dp/.*",
            r"/pd/.*",
            r"-p-\d+",
        ]
        category_regexes = [
            r"/category/.*",
            r"/c/.*",
            r"/collections/.*",
            r"/dept/.*",
            r"/browse/.*",
        ]

        prod_matches = set()
        cat_matches = set()

        for url in urls:
            path = urlsplit(url).path
            for rx in product_regexes:
                if re.search(rx, path, re.I):
                    prod_matches.add(rx)
            for rx in category_regexes:
                if re.search(rx, path, re.I):
                    cat_matches.add(rx)

        profile.product_url_patterns = list(prod_matches) if prod_matches else [r"/p/", r"/product/"]
        profile.category_url_patterns = list(cat_matches) if cat_matches else [r"/c/", r"/category/"]
