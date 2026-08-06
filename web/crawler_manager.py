import asyncio
import json
import logging
import time
import re
from typing import Dict, List, Any
from urllib.parse import urlsplit

from shared.utils.config import get_config
from shared.models import CrawlTask, ClassifiedURL
from shared.utils.url_normalizer import normalize_url
from shared.utils.scope_manager import ScopeManager
from mcps.discovery.discovery_mcp import DiscoveryMCP
from mcps.classification.classification_mcp import ClassificationMCP
from mcps.execution.execution_mcp import ExecutionMCP
from mcps.extraction.extraction_mcp import ExtractionMCP
from mcps.validation.validation_mcp import ValidationMCP
from mcps.storage.storage_mcp import StorageMCP

class WebCrawlSession:
    def __init__(self, seed_url: str, limit: int):
        self.seed_url = seed_url
        self.limit = limit
        self.status = "idle"
        self.pages_visited = 0
        self.products_scraped = 0
        self.listeners: List[asyncio.Queue] = []
        self.products = []

        # Crawl session resume state variables
        self.is_initialized = False
        self.queue = []
        self.visited_navigation_hubs = set()
        self.visited_categories = set()
        self.visited_product_families = set()
        self.visited_product_pages = set()
        self.seen_product_titles = set()
        self.prefix_failures = {}
        self.dead_prefixes = set()
        self.disc_res = None
        self.scope_manager = None
        self.coverage_report = {}

        # Crawl Metrics
        self.urls_discovered = 0
        self.urls_after_scope_filter = 0
        self.duplicates_removed = 0
        self.navigation_hubs_expanded = 0
        self.categories_expanded = 0
        self.product_families_expanded = 0
        self.products_detected = 0
        self.products_exported = 0
        self.terminal_branches = 0
        self.playwright_pages = 0
        self.llm_classifications = 0
        self.crawl_start_time = 0.0

    def register_listener(self) -> asyncio.Queue:
        q = asyncio.Queue()
        self.listeners.append(q)
        # Seed currently loaded state to new listener
        for p in self.products:
            q.put_nowait({"type": "product", "data": p})
        q.put_nowait({"type": "status", "data": {"status": self.status}})
        q.put_nowait({"type": "stats", "data": {
            "pages_visited": self.pages_visited,
            "products_scraped": self.products_scraped
        }})
        return q

    def unregister_listener(self, q: asyncio.Queue):
        if q in self.listeners:
            self.listeners.remove(q)

    def log(self, level: str, message: str):
        evt = {"type": "log", "data": {"level": level, "message": message}}
        for q in self.listeners:
            q.put_nowait(evt)

    def set_status(self, status: str):
        self.status = status
        evt = {"type": "status", "data": {"status": status}}
        for q in self.listeners:
            q.put_nowait(evt)

    def emit_stats(self):
        evt = {"type": "stats", "data": {
            "pages_visited": self.pages_visited,
            "products_scraped": self.products_scraped
        }}
        for q in self.listeners:
            q.put_nowait(evt)

    def emit_product(self, product_data: Dict[str, Any]):
        self.products.append(product_data)
        evt = {"type": "product", "data": product_data}
        for q in self.listeners:
            q.put_nowait(evt)

    def _log_traversal_diagnostics(
        self,
        url: str,
        item: Any,
        fetch_res: Any,
        candidate_count: int,
        norm_count: int,
        dup_count: int,
        scope_count: int,
        class_summary: str,
        enqueued_count: int,
        prod_detected: int,
        prod_exported: int,
        term_reason: str
    ) -> None:
        """Logs detailed traversal diagnostics for auditing page processing."""
        html = fetch_res.html or ""
        dom_size = len(html)
        anchor_count = html.count("<a ")
        
        self.log(
            "INFO",
            "\n"
            "====================================================\n"
            "               TRAVERSAL DIAGNOSTICS\n"
            "====================================================\n"
            f"Current URL:                  {url}\n"
            f"Detected page type:           {item.page_type}\n"
            f"Navigation Intent confidence: {item.confidence}\n"
            f"Rendered DOM size:            {dom_size} bytes\n"
            f"Anchor count:                 {anchor_count}\n"
            f"Candidate links extracted:    {candidate_count}\n"
            f"Links after normalization:    {norm_count}\n"
            f"Links after duplicate remove:  {dup_count}\n"
            f"Links after scope validation: {scope_count}\n"
            f"Classification summary:       {class_summary}\n"
            f"Links enqueued:               {enqueued_count}\n"
            f"Products detected:            {prod_detected}\n"
            f"Products exported:            {prod_exported}\n"
            f"Termination reason:           {term_reason}\n"
            "===================================================="
        )

    async def execute_crawl(self):
        self.set_status("running")
        self.log("SYSTEM", "Loading configurations...")
        config = get_config()
        
        # Override output location to make it downloadable
        config.output.directory = Path("outputs/")
        config.output.directory.mkdir(parents=True, exist_ok=True)

        execution = ExecutionMCP(config)
        discovery = DiscoveryMCP(config, playwright_mcp=execution.playwright)
        classification = ClassificationMCP()
        extraction = ExtractionMCP(config)
        validation = ValidationMCP()
        storage = StorageMCP(config)

        try:
            def get_branch_name(target_url: str) -> str:
                parts = urlsplit(target_url)
                segments = [s for s in parts.path.split("/") if s]
                locale_re = re.compile(r"^[a-z]{2}([-_][a-z]{2,4})?$", re.IGNORECASE)
                if segments and locale_re.match(segments[0]):
                    segments.pop(0)
                if segments and locale_re.match(segments[0]):  # handles nested /en/us/
                    segments.pop(0)
                return segments[0].capitalize() if segments else "Root"

            if not self.is_initialized:
                # Clear previous products files so each new crawl session starts fresh
                for fname in ("products.csv", "products.ndjson", "products.db"):
                    fpath = config.output.directory / fname
                    if fpath.exists():
                        try:
                            fpath.unlink()
                        except Exception as e:
                            self.log("WARNING", f"Could not clear old file {fname}: {e}")

                # Clear individual product JSON files from the previous crawl
                products_json_dir = config.output.directory / "products"
                if products_json_dir.exists():
                    for old_json in products_json_dir.glob("*.json"):
                        try:
                            old_json.unlink()
                        except Exception as e:
                            self.log("WARNING", f"Could not clear old product JSON {old_json.name}: {e}")

                task = CrawlTask(
                    seed_url=self.seed_url,
                    domain=urlsplit(self.seed_url).netloc,
                    max_pages=self.limit * 10
                )

                self.log("INFO", f"Starting discovery phase on {self.seed_url}...")
                self.emit_stats()
                self.disc_res = await discovery.discover(task)
                self.log("SUCCESS", f"Discovery finished. Crawled seed pages, extracted menu layout, parsed robots/sitemaps.")
                self.log("INFO", f"Discovered {len(self.disc_res.urls)} total URLs in sitemaps/navigation menu.")

                # Crawl metrics
                self.urls_discovered = len(self.disc_res.urls)
                self.urls_after_scope_filter = 0
                self.duplicates_removed = 0
                self.navigation_hubs_expanded = 0
                self.categories_expanded = 0
                self.product_families_expanded = 0
                self.products_detected = 0
                self.products_exported = 0
                self.terminal_branches = 0
                self.playwright_pages = 0
                self.llm_classifications = 0
                self.crawl_start_time = time.time()
                self.coverage_report = {}

                # Instantiate ScopeManager
                self.scope_manager = ScopeManager(self.seed_url, policy=config.crawl_scope.policy)

                # Visited sets (independent for navigation memory)
                self.visited_navigation_hubs = set()
                self.visited_categories = set()
                self.visited_product_families = set()
                self.visited_product_pages = set()
                self.seen_product_titles = set()

                # Track seed URL
                self.visited_navigation_hubs.add(self.scope_manager.normalize(self.seed_url))
                
                # Traversal Priority Queue
                self.queue = []
                
                # Path prefix failure tracking to detect and prune stale/dead sitemap directories
                self.prefix_failures = {}
                self.dead_prefixes = set()

                # Initial batch classification
                candidate_urls = []
                for url in self.disc_res.urls:
                    decision = self.scope_manager.validate(
                        url,
                        source_page="sitemap",
                        discovery_method="sitemap_import",
                    )
                    if decision.decision == "REJECT_DUPLICATE":
                        self.duplicates_removed += 1
                    if decision.decision == "ACCEPT":
                        self.urls_after_scope_filter += 1
                        candidate_urls.append(decision.normalized_url)

                self.log("INFO", f"Classifying initial batch of {len(candidate_urls)} discovered URLs...")
                
                batch_size = 50
                for i in range(0, len(candidate_urls), batch_size):
                    if self.status != "running":
                        break
                    batch = candidate_urls[i:i+batch_size]
                    classified_batch = await classification.classify(batch, self.disc_res.profile, None)
                    self.log("INFO", f"Classified {i + len(batch)}/{len(candidate_urls)} URLs...")
                    for item in classified_batch:
                        if item.page_type in ("PRODUCT", "PRODUCT_FAMILY", "CATEGORY", "NAVIGATION_HUB", "UNKNOWN"):
                            # Map intent priorities
                            if item.page_type == "PRODUCT":
                                item.priority = 3
                            elif item.page_type in ("PRODUCT_FAMILY", "NAVIGATION_HUB"):
                                item.priority = 2
                            elif item.page_type == "CATEGORY":
                                item.priority = 1
                            else:
                                item.priority = 0
                            # Assign nav_position from the discovery nav map so
                            # left-side nav items (products) are visited before
                            # right-side utility sections (shop, experience, racing…)
                            item.nav_position = self.disc_res.nav_url_positions.get(item.url, 9999)
                            self.queue.append(item)

                # Sort queue: priority DESC, confidence DESC, nav_position ASC (left = smaller), depth ASC
                self.queue.sort(key=lambda x: (x.priority, x.confidence, -x.nav_position, -x.depth), reverse=True)
                self.is_initialized = True

            else:
                self.log("INFO", f"Resuming crawl session from page {self.pages_visited}...")
                self.log("INFO", f"Remaining queue size: {len(self.queue)} URLs.")

            def register_path_failure(failed_url: str) -> None:
                try:
                    parts = urlsplit(failed_url)
                    path_segs = [s for s in parts.path.strip("/").split("/") if s]
                    # We only track prefix lengths of 3 to len(path_segs) - 1 to avoid broad domains or locales
                    for length in range(3, len(path_segs)):
                        prefix = "/" + "/".join(path_segs[:length])
                        self.prefix_failures[prefix] = self.prefix_failures.get(prefix, 0) + 1
                        if self.prefix_failures[prefix] >= 5:
                            if prefix not in self.dead_prefixes:
                                self.dead_prefixes.add(prefix)
                                self.log("WARNING", f"Stale route prefix detected: '{prefix}' has failed 5 times with 404/Soft-404. Pruning matching queue items.")
                                before_len = len(self.queue)
                                self.queue = [item for item in self.queue if not urlsplit(item.url).path.lower().startswith(prefix.lower())]
                                self.log("INFO", f"Pruned {before_len - len(self.queue)} URLs from traversal queue matching stale prefix '{prefix}'.")
                except Exception as ex:
                    self.log("ERROR", f"Error in register_path_failure: {str(ex)}")

            queue = self.queue
            visited_navigation_hubs = self.visited_navigation_hubs
            visited_categories = self.visited_categories
            visited_product_families = self.visited_product_families
            visited_product_pages = self.visited_product_pages
            seen_product_titles = self.seen_product_titles
            dead_prefixes = self.dead_prefixes
            disc_res = self.disc_res
            scope_manager = self.scope_manager
            coverage_report = self.coverage_report

            urls_discovered = self.urls_discovered
            urls_after_scope_filter = self.urls_after_scope_filter
            duplicates_removed = self.duplicates_removed
            navigation_hubs_expanded = self.navigation_hubs_expanded
            categories_expanded = self.categories_expanded
            product_families_expanded = self.product_families_expanded
            products_detected = self.products_detected
            products_exported = self.products_exported
            terminal_branches = self.terminal_branches
            playwright_pages = self.playwright_pages
            llm_classifications = self.llm_classifications
            crawl_start_time = self.crawl_start_time

            self.log("INFO", f"Starting Page Understanding Navigation intent traversal loop...")
            
            while queue and self.products_scraped < self.limit and self.status == "running":
                # Get next highest priority/confidence candidate
                c_url = queue.pop(0)
                url = c_url.url
                norm_url = scope_manager.normalize(url)
                
                # Check visited state according to page type (Navigation Memory)
                if c_url.page_type == "PRODUCT" and norm_url in visited_product_pages:
                    continue
                elif c_url.page_type == "CATEGORY" and norm_url in visited_categories:
                    continue
                elif c_url.page_type == "PRODUCT_FAMILY" and norm_url in visited_product_families:
                    continue
                elif c_url.page_type == "NAVIGATION_HUB" and norm_url in visited_navigation_hubs:
                    continue
                elif c_url.page_type == "UNKNOWN" and norm_url in (visited_product_pages | visited_categories | visited_product_families | visited_navigation_hubs):
                    continue

                # Skip URLs belonging to dead prefixes (e.g. stale accessories sections)
                url_path = urlsplit(norm_url).path.lower()
                if any(url_path.startswith(dp.lower()) for dp in dead_prefixes):
                    continue

                # Add to appropriate visited set
                if c_url.page_type == "PRODUCT":
                    visited_product_pages.add(norm_url)
                elif c_url.page_type == "CATEGORY":
                    visited_categories.add(norm_url)
                elif c_url.page_type == "PRODUCT_FAMILY":
                    visited_product_families.add(norm_url)
                elif c_url.page_type == "NAVIGATION_HUB":
                    visited_navigation_hubs.add(norm_url)
                elif c_url.page_type == "UNKNOWN":
                    # Track unknown URL as processed to avoid double crawling
                    visited_product_pages.add(norm_url)

                # Initialize branch coverage record
                branch = get_branch_name(url)
                if branch not in coverage_report:
                    coverage_report[branch] = {
                        "branch_name": branch,
                        "nav_type": str(c_url.page_type),
                        "expanded": False,
                        "products_found": 0,
                        "products_exported": 0,
                        "termination_reason": ""
                    }

                self.pages_visited += 1
                self.log("INFO", f"[{self.pages_visited}] Processing {c_url.page_type} page: {url}")
                self.emit_stats()

                try:
                    # Diagnostics metrics
                    candidate_count = 0
                    norm_count = 0
                    dup_count = 0
                    scope_count = 0
                    class_summary = "N/A"
                    enqueued_count = 0
                    prod_detected = 0
                    prod_exported = 0

                    fetch_res = await execution.smart_fetch(url, disc_res.profile)
                    if fetch_res.from_cache is False:
                        playwright_pages += 1
                    
                    if not fetch_res.success or not fetch_res.html:
                        self.log("WARNING", f"Failed to fetch content from {url}")
                        if getattr(fetch_res, "status_code", None) in (404, 410):
                            register_path_failure(url)
                        coverage_report[branch]["termination_reason"] = "Fetch failed"
                        self._log_traversal_diagnostics(url, c_url, fetch_res, candidate_count, norm_count, dup_count, scope_count, class_summary, enqueued_count, prod_detected, prod_exported, "Fetch failed")
                        continue

                    # Re-classify page with full HTML snippet
                    re_classified = await classification.classify([url], disc_res.profile, execution)
                    item = re_classified[0]
                    if "LLM Classification" in "".join(item.signals_fired):
                        llm_classifications += 1

                    self.log("INFO", f"Classification: {item.page_type} (Confidence: {int(item.confidence * 100)}%)")

                    if item.page_type in ("PRODUCT", "PRODUCT_FAMILY"):
                        products_detected += 1
                        prod_detected = 1
                        coverage_report[branch]["products_found"] += 1
                        coverage_report[branch]["nav_type"] = str(item.page_type)

                        # --- Soft-404 / bot-wall detection ---
                        # Separate two cases:
                        #   1. Genuine soft-404: page URL is dead → skip entirely
                        #   2. Bot-wall: URL is valid but server blocked us → save with URL-derived title
                        _genuine_404_phrases = [
                            "page not found", "error 404", "404 error",
                            "page doesn't exist", "page does not exist",
                            "this page is unavailable", "no page found",
                            "we can't find", "we could not find", "page unavailable",
                        ]
                        _bot_wall_phrases = [
                            "are you a robot", "robot check", "human verification",
                            "access denied", "just a moment",
                            "please verify you are a human", "security check",
                            "enable javascript and cookies", "ddos protection",
                        ]
                        from bs4 import BeautifulSoup as _BS
                        _title_check_soup = _BS(fetch_res.html, "html.parser")
                        _page_title = (_title_check_soup.title.get_text() if _title_check_soup.title else "").lower()
                        _h1_tags = _title_check_soup.find_all("h1")
                        _h1_text = " ".join(h.get_text() for h in _h1_tags).lower()

                        _is_genuine_404 = any(
                            phrase in _page_title or phrase in _h1_text
                            for phrase in _genuine_404_phrases
                        )
                        _is_bot_wall = any(
                            phrase in _page_title or phrase in _h1_text
                            for phrase in _bot_wall_phrases
                        )
                        # Secondary: tiny DOM (<25KB, <10 links) → bot-wall, not dead link
                        _html_size = len(fetch_res.html or "")
                        _anchor_count = len(_title_check_soup.find_all("a", href=True))
                        if not _is_genuine_404 and not _is_bot_wall and _html_size < 25000 and _anchor_count < 10:
                            _is_bot_wall = True

                        if _is_genuine_404:
                            # Dead URL — skip entirely, no product to save
                            self.log("WARNING", f"Soft-404 detected on {url} (title: '{_page_title[:80]}'). Skipping.")
                            register_path_failure(url)
                            coverage_report[branch]["termination_reason"] = "Soft-404 detected"
                            products_detected -= 1
                            prod_detected = 0
                            coverage_report[branch]["products_found"] -= 1
                            self._log_traversal_diagnostics(url, item, fetch_res, candidate_count, norm_count, dup_count, scope_count, class_summary, enqueued_count, prod_detected, prod_exported, "Soft-404")
                            continue

                        if _is_bot_wall:
                            # Valid URL but blocked by bot protection → derive title from URL path
                            from urllib.parse import urlsplit as _urlsplit
                            from shared.models.product import Product as _Product
                            from shared.models.extraction_result import ExtractionResult as _ExtrResult
                            _path_segs = [s for s in _urlsplit(url).path.strip("/").split("/") if s]

                            # Walk backwards through URL segments to find the model code.
                            # Model codes always contain at least one digit (e.g. E26, CT2025, 316).
                            # Section/tab names are all-alpha (e.g. "feature", "instrumentation",
                            # "machine-protection") — these are sub-pages, NOT products.
                            _model_slug = None
                            _category_slug = None
                            for _i in range(len(_path_segs) - 1, -1, -1):
                                _seg = _path_segs[_i]
                                if any(c.isdigit() for c in _seg):
                                    _model_slug = _seg
                                    _category_slug = _path_segs[_i - 1] if _i > 0 else None
                                    break

                            if _model_slug is None:
                                # No segment with a digit found → this is a section/tab page,
                                # not a real product. Skip it entirely.
                                self.log("WARNING", f"Bot-wall on {url} — no model code in URL path; likely a sub-page. Skipping.")
                                coverage_report[branch]["termination_reason"] = "Bot-wall (sub-page, no model code)"
                                products_detected -= 1
                                prod_detected = 0
                                coverage_report[branch]["products_found"] -= 1
                                self._log_traversal_diagnostics(url, item, fetch_res, candidate_count, norm_count, dup_count, scope_count, class_summary, enqueued_count, prod_detected, prod_exported, "Bot-wall sub-page skipped")
                                continue

                            _derived_title = _model_slug.replace("-", " ").replace("_", " ").upper()
                            _derived_category = _category_slug.replace("-", " ").title() if _category_slug else None
                            _domain = _urlsplit(url).netloc
                            _bot_product = _Product(
                                source_url=url,
                                domain=_domain,
                                title=_derived_title,
                                brand=disc_res.profile.domain.split(".")[0].capitalize() if disc_res.profile.domain else None,
                                category=_derived_category,
                                extraction_method="none",
                                extraction_confidence=0.4,
                            )
                            _bot_extract = _ExtrResult(
                                success=True,
                                product=_bot_product,
                                method="none",
                                confidence=0.4,
                                warnings=["Bot-wall detected; title derived from URL path"],
                            )
                            self.log("WARNING", f"Bot-wall on {url} — saving with URL-derived title: '{_derived_title}'")
                            # Title-based cross-listing dedup
                            _norm_title = _derived_title.strip().lower()
                            if _norm_title in seen_product_titles:
                                self.log("INFO", f"Duplicate title '{_derived_title}' already stored this session (cross-listing). Skipping {url}")
                                products_detected -= 1
                                prod_detected = 0
                                coverage_report[branch]["products_found"] -= 1
                                self._log_traversal_diagnostics(url, item, fetch_res, candidate_count, norm_count, dup_count, scope_count, class_summary, enqueued_count, prod_detected, prod_exported, "Duplicate title (cross-listing)")
                                continue
                            val_res_bot = await validation.validate(_bot_extract)
                            store_res_bot = await storage.write(_bot_product, val_res_bot)
                            if store_res_bot.success:
                                seen_product_titles.add(_norm_title)
                                self.products_scraped += 1
                                products_exported += 1
                                prod_exported = 1
                                coverage_report[branch]["products_exported"] += 1
                                self.emit_product({"title": _derived_title, "price": None, "brand": _bot_product.brand, "url": url})
                                self.log("SUCCESS", f"Stored product (bot-wall, URL-derived): '{_derived_title}'")
                                self.emit_stats()
                            self._log_traversal_diagnostics(url, item, fetch_res, candidate_count, norm_count, dup_count, scope_count, class_summary, enqueued_count, prod_detected, prod_exported, "Bot-wall (URL-derived title)")
                            continue


                        # Extract details
                        extract_res = await extraction.extract(fetch_res.html, disc_res.profile, url=url)
                        if not extract_res.success or not extract_res.product:
                            self.log("WARNING", f"Extraction failed for {url}")
                            coverage_report[branch]["termination_reason"] = "Extraction failed"
                            self._log_traversal_diagnostics(url, item, fetch_res, candidate_count, norm_count, dup_count, scope_count, class_summary, enqueued_count, prod_detected, prod_exported, "Extraction failed")
                            continue

                        # Validate details
                        val_res = await validation.validate(extract_res)
                        if val_res.verdict == "FAIL":
                            self.log("WARNING", f"Product skipped. Validation failed: {val_res.errors}")
                            coverage_report[branch]["termination_reason"] = f"Validation failed: {val_res.errors}"
                            self._log_traversal_diagnostics(url, item, fetch_res, candidate_count, norm_count, dup_count, scope_count, class_summary, enqueued_count, prod_detected, prod_exported, f"Validation failed: {val_res.errors}")
                            continue

                        # Title-based cross-listing dedup: skip if same title already stored
                        _norm_extracted_title = (extract_res.product.title or "").strip().lower()
                        if _norm_extracted_title and _norm_extracted_title in seen_product_titles:
                            self.log("INFO", f"Duplicate title '{extract_res.product.title}' already stored this session (cross-listing). Skipping {url}")
                            products_detected -= 1
                            prod_detected = 0
                            coverage_report[branch]["products_found"] -= 1
                            self._log_traversal_diagnostics(url, item, fetch_res, candidate_count, norm_count, dup_count, scope_count, class_summary, enqueued_count, prod_detected, prod_exported, "Duplicate title (cross-listing)")
                            continue

                        # Persist details
                        store_res = await storage.write(extract_res.product, val_res)
                        if store_res.success:
                            seen_product_titles.add(_norm_extracted_title)
                            self.products_scraped += 1
                            products_exported += 1
                            prod_exported = 1
                            coverage_report[branch]["products_exported"] += 1
                            prod_data = {
                                "title": extract_res.product.title,
                                "price": extract_res.product.price,
                                "brand": extract_res.product.brand,
                                "url": url
                            }
                            self.emit_product(prod_data)
                            self.log("SUCCESS", f"Stored product: '{extract_res.product.title}' at Price: {extract_res.product.price} {extract_res.product.currency}")
                            self.emit_stats()
                        else:
                            self.log("ERROR", f"Failed to write product data to storage: {store_res.error}")

                    elif item.page_type in ("CATEGORY", "PRODUCT_FAMILY", "NAVIGATION_HUB"):
                        # Mark expanded
                        coverage_report[branch]["expanded"] = True
                        coverage_report[branch]["nav_type"] = str(item.page_type)

                        if item.page_type == "CATEGORY":
                            categories_expanded += 1
                        elif item.page_type == "PRODUCT_FAMILY":
                            # --- Multi-product listing guard ---
                            # If this PRODUCT_FAMILY page actually contains a grid of multiple
                            # product cards (e.g. "MEN'S APPAREL" listing), treat it as a
                            # CATEGORY (expand links, don't extract). This is purely structural
                            # DOM counting — no site-specific logic.
                            from bs4 import BeautifulSoup as _GuardBS
                            _guard_soup = _GuardBS(fetch_res.html, "html.parser")
                            _product_card_count = len(_guard_soup.find_all(
                                class_=re.compile(
                                    r"product[-_]?(?:card|tile|item|grid|cell|block|thumb|listing)|item[-_]?card|grid[-_]?item",
                                    re.I,
                                )
                            ))
                            if _product_card_count > 3:
                                self.log(
                                    "INFO",
                                    f"PRODUCT_FAMILY guard: {_product_card_count} product cards found on {url}. "
                                    f"Treating as listing page — expanding links only, not extracting.",
                                )
                                # Redirect to expand-links path (falls through to CATEGORY handling below)
                                item.page_type = "CATEGORY"
                                categories_expanded += 1
                            else:
                                product_families_expanded += 1
                        elif item.page_type == "NAVIGATION_HUB":
                            navigation_hubs_expanded += 1

                        # Extract outbound links from category page to traverse deeper
                        from bs4 import BeautifulSoup
                        soup = BeautifulSoup(fetch_res.html, "html.parser")
                        all_anchors = soup.find_all("a", href=True)

                        # Generic dynamic grid check: if page is listing but HTTP requests returned fewer than 15 links,
                        # it indicates client-side dynamic rendering. Escalate to Playwright and re-fetch!
                        if fetch_res.fetch_method == "requests" and len(all_anchors) < 15:
                            self.log("INFO", f"Detected low link density ({len(all_anchors)} links) on catalog listing page. Escalating to Playwright...")
                            disc_res.profile.preferred_fetch_method = "playwright"
                            fetch_res = await execution.smart_fetch(url, disc_res.profile)
                            soup = BeautifulSoup(fetch_res.html, "html.parser")
                            all_anchors = soup.find_all("a", href=True)

                        candidate_count = len(all_anchors)
                        new_links = []
                        for a in all_anchors:
                            href = a["href"]
                            from urllib.parse import urljoin
                            abs_url = urljoin(url, href).split("#")[0]
                            
                            path_lower = urlsplit(abs_url).path.lower()
                            if not any(path_lower.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".gif", ".css", ".js", ".pdf", ".xml")):
                                norm_count += 1
                                # Validate ScopeManager
                                decision = scope_manager.validate(
                                    abs_url,
                                    source_page=url,
                                    discovery_method="anchor_tag",
                                )
                                if decision.decision == "REJECT_DUPLICATE":
                                    duplicates_removed += 1
                                    dup_count += 1
                                if decision.decision == "ACCEPT":
                                    urls_after_scope_filter += 1
                                    scope_count += 1
                                    new_links.append(decision.normalized_url)

                        new_links = list(set(new_links))
                        urls_discovered += len(new_links)

                        if new_links:
                            self.log("INFO", f"Discovered {len(new_links)} new candidate links on {url}. Classifying...")
                            new_classified = await classification.classify(new_links, disc_res.profile, None)
                            
                            class_counts = {}
                            for nc_item in new_classified:
                                class_counts[nc_item.page_type] = class_counts.get(nc_item.page_type, 0) + 1
                            class_summary = ", ".join(f"{k}: {v}" for k, v in class_counts.items())

                            enqueued_count = 0
                            for new_item in new_classified:
                                # Add to queue if matches target page categories
                                if new_item.page_type in ("PRODUCT", "PRODUCT_FAMILY", "CATEGORY", "NAVIGATION_HUB"):
                                    if new_item.page_type == "PRODUCT":
                                        new_item.priority = 3
                                    elif new_item.page_type in ("PRODUCT_FAMILY", "NAVIGATION_HUB"):
                                        new_item.priority = 2
                                    elif new_item.page_type == "CATEGORY":
                                        new_item.priority = 1
                                    # Propagate nav_position if the URL appeared in the nav map
                                    new_item.nav_position = disc_res.nav_url_positions.get(new_item.url, 9999)
                                    queue.append(new_item)
                                    enqueued_count += 1

                            if enqueued_count > 0:
                                self.log("INFO", f"Enqueued {enqueued_count} new traversable pages into the queue.")
                                # Re-sort the queue with nav_position tiebreaker
                                queue.sort(key=lambda x: (x.priority, x.confidence, -x.nav_position, -x.depth), reverse=True)
                            else:
                                if not coverage_report[branch]["termination_reason"]:
                                    coverage_report[branch]["termination_reason"] = "No downstream products"

                    else:
                        # Ignore other page types (terminates traversal)
                        terminal_branches += 1
                        coverage_report[branch]["termination_reason"] = f"Terminal Page Type: {item.page_type}"
                        self.log("INFO", f"Ignoring non-catalog page type: {item.page_type}")

                    # Log traversal diagnostics for the processed page
                    term_reason = coverage_report[branch]["termination_reason"] or "N/A"
                    self._log_traversal_diagnostics(
                        url=url,
                        item=item,
                        fetch_res=fetch_res,
                        candidate_count=candidate_count,
                        norm_count=norm_count,
                        dup_count=dup_count,
                        scope_count=scope_count,
                        class_summary=class_summary,
                        enqueued_count=enqueued_count,
                        prod_detected=prod_detected,
                        prod_exported=prod_exported,
                        term_reason=term_reason
                    )

                except Exception as e:
                    self.log("ERROR", f"Failed to process URL {url}: {str(e)}")

            # Crawl Duration
            crawl_duration = round(time.time() - crawl_start_time, 2)

            # Print Crawl Coverage Report
            self.log("SUCCESS", "\n=======================================================\n"
                                  "               CRAWL COVERAGE REPORT\n"
                                  "=======================================================")
            for b_name, b_info in coverage_report.items():
                expanded_str = "Expanded" if b_info["expanded"] else "Skipped"
                reason_str = f" (Reason: {b_info['termination_reason']})" if b_info["termination_reason"] else ""
                self.log("SUCCESS", f"Branch: {b_name} | Type: {b_info['nav_type']} | status: {expanded_str} | Found: {b_info['products_found']} | Exported: {b_info['products_exported']}{reason_str}")

            # Print Crawl Statistics
            self.log("SUCCESS", "\n=======================================================\n"
                                  "               CRAWL STATISTICS\n"
                                  "=======================================================")
            self.log("SUCCESS", f"urls_discovered: {urls_discovered}")
            self.log("SUCCESS", f"urls_after_scope_filter: {urls_after_scope_filter}")
            self.log("SUCCESS", f"duplicates_removed: {duplicates_removed}")
            self.log("SUCCESS", f"navigation_hubs_expanded: {navigation_hubs_expanded}")
            self.log("SUCCESS", f"categories_expanded: {categories_expanded}")
            self.log("SUCCESS", f"product_families_expanded: {product_families_expanded}")
            self.log("SUCCESS", f"products_detected: {products_detected}")
            self.log("SUCCESS", f"products_exported: {products_exported}")
            self.log("SUCCESS", f"terminal_branches: {terminal_branches}")
            self.log("SUCCESS", f"playwright_pages: {playwright_pages}")
            self.log("SUCCESS", f"llm_classifications: {llm_classifications}")
            self.log("SUCCESS", f"crawl_duration: {crawl_duration}s")
            self.log("SUCCESS", "=======================================================")

            # Persist integer metrics back to self
            self.urls_discovered = urls_discovered
            self.urls_after_scope_filter = urls_after_scope_filter
            self.duplicates_removed = duplicates_removed
            self.navigation_hubs_expanded = navigation_hubs_expanded
            self.categories_expanded = categories_expanded
            self.product_families_expanded = product_families_expanded
            self.products_detected = products_detected
            self.products_exported = products_exported
            self.terminal_branches = terminal_branches
            self.playwright_pages = playwright_pages
            self.llm_classifications = llm_classifications

            if self.status == "running":
                self.log("SUCCESS", f"Crawl finished. Successfully processed and exported {self.products_scraped} products.")
                self.set_status("completed")
            else:
                self.log("WARNING", f"Crawl paused. Processed {self.pages_visited} pages, found {self.products_scraped} products.")
                # Keep status as stopped/paused so resume is possible
    

        except Exception as e:
            self.log("ERROR", f"Crawl crashed: {str(e)}")
            self.set_status("failed")
        finally:
            await execution.close()
            await storage.close()

from pathlib import Path
