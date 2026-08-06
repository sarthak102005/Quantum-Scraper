"""
mcps/extraction/extraction_mcp.py

Extraction MCP — implements the 5-stage extraction pipeline:
JSON-LD → CSS Selectors → XPath → Semantic DOM → LLM Fallback.
"""

from __future__ import annotations

from mcps.extraction import (
    jsonld_extractor,
    llm_extractor,
    selector_extractor,
    semantic_extractor,
)
from shared.models.extraction_result import ExtractionResult
from shared.models.website_profile import WebsiteProfile
from shared.models.product import Product
from shared.utils.config import Config, get_config
from shared.utils.logging import get_logger

logger = get_logger(__name__)


class ExtractionMCP:
    """Pipelines extraction logic sequentially down structured fallback stages."""

    def __init__(self, config: Config | None = None) -> None:
        self.config = config or get_config()

    async def extract(
        self,
        html: str,
        profile: WebsiteProfile,
        url: str | None = None,
    ) -> ExtractionResult:
        """Run HTML page content through 5 stages of extraction.

        Args:
            html: HTML source.
            profile: Contextual WebsiteProfile.
            url: Optional actual page URL.

        Returns:
            ExtractionResult.
        """
        source_url = url or profile.seed_url
        logger.info("Orchestrating extraction pipeline", url=source_url)

        # Stage 1: JSON-LD Extractor (target confidence: 0.90+)
        res_ld = await jsonld_extractor.extract(html, source_url)
        if res_ld.success and res_ld.confidence >= 0.90 and self._has_required_fields(res_ld, allow_enrichment=True):
            logger.info("Pipeline matched Stage 1: JSON-LD")
            await self._enrich_product(res_ld.product, html, source_url)
            return res_ld

        # Stage 2: CSS Selectors (target confidence: 0.85+)
        selector_set = profile.get_active_selector_set()
        res_css = await selector_extractor.extract(html, selector_set, method="css", source_url=source_url)
        if res_css.success and res_css.confidence >= 0.85 and self._has_required_fields(res_css, allow_enrichment=True):
            logger.info("Pipeline matched Stage 2: CSS Selectors")
            await self._enrich_product(res_css.product, html, source_url)
            return res_css

        # Stage 3: XPath Selectors (target confidence: 0.80+)
        res_xpath = await selector_extractor.extract(html, selector_set, method="xpath", source_url=source_url)
        if res_xpath.success and res_xpath.confidence >= 0.80 and self._has_required_fields(res_xpath, allow_enrichment=True):
            logger.info("Pipeline matched Stage 3: XPath")
            await self._enrich_product(res_xpath.product, html, source_url)
            return res_xpath

        # Stage 4: Semantic DOM inference (target confidence: 0.70+)
        res_sem = await semantic_extractor.extract(html, source_url)
        if res_sem.success and res_sem.confidence >= 0.70 and self._has_required_fields(res_sem, allow_enrichment=False):
            logger.info("Pipeline matched Stage 4: Semantic DOM")
            return res_sem

        # Stage 5: LLM fallback (if enabled)
        if self.config.llm.extraction_fallback_enabled:
            res_llm = await llm_extractor.extract(html, source_url, self.config)
            if res_llm.success:
                logger.info("Pipeline matched Stage 5: LLM Fallback")
                return res_llm

        # If all stages failed, return highest confidence attempt or default failure
        logger.warning("Pipeline extraction failed all stages", url=source_url)
        candidates = [res_ld, res_css, res_xpath, res_sem]
        candidates.sort(key=lambda x: x.confidence, reverse=True)
        return candidates[0]

    def _has_required_fields(self, res: ExtractionResult, allow_enrichment: bool = False) -> bool:
        """Helper validating that required fields are present."""
        if not res.product:
            return False
        p = res.product
        return bool(p.title and p.title.strip())

    async def _enrich_product(self, product: Product, html: str, source_url: str) -> None:
        """Enrich extracted product with DOM description and specifications if missing."""
        from bs4 import BeautifulSoup
        import re

        soup = BeautifulSoup(html, "lxml")

        # 1. Parse specifications if empty
        if not product.specifications:
            specifications = {}
            tables = soup.find_all(re.compile(r"table|dl", re.I), class_=re.compile(r"spec|detail|attrib|feature|tech|dimension", re.I))
            for t in tables:
                if t.name == "table":
                    for row in t.find_all("tr"):
                        th = row.find(["th", "td"], class_=re.compile(r"label|title|header", re.I)) or row.find("th")
                        tds = row.find_all("td")
                        td = tds[1] if len(tds) > 1 else (tds[0] if tds else None)
                        if th and td and th != td:
                            key = th.get_text().strip().replace(":", "")
                            val = td.get_text().strip()
                            if key and val:
                                specifications[key] = val
                elif t.name == "dl":
                    dts = t.find_all("dt")
                    dds = t.find_all("dd")
                    for dt, dd in zip(dts, dds):
                        key = dt.get_text().strip().replace(":", "")
                        val = dd.get_text().strip()
                        if key and val:
                            specifications[key] = val

            spec_headings = []
            for tag in ["h2", "h3", "h4", "h5", "div", "p"]:
                for el in soup.find_all(tag):
                    txt = el.get_text().strip().lower()
                    if any(term in txt for term in ["specification", "specs", "technical", "dimension", "feature"]):
                        spec_headings.append(el)

            for heading in spec_headings:
                parent = heading.parent
                list_items = parent.find_all("li") if parent else []
                if not list_items:
                    sibling = heading.next_sibling
                    while sibling and not list_items:
                        if hasattr(sibling, "find_all"):
                            list_items = sibling.find_all("li")
                        sibling = sibling.next_sibling
                for li in list_items:
                    text = li.get_text().strip()
                    if ":" in text:
                        parts = text.split(":", 1)
                        k = parts[0].strip()
                        v = parts[1].strip()
                        if len(k) < 50 and v:
                            specifications[k] = v

            if not specifications:
                spec_items = soup.find_all(["li", "div", "p"], class_=re.compile(r"spec|attribute|feature|tech", re.I))
                for item in spec_items:
                    text = item.get_text().strip()
                    if ":" in text and "\n" not in text:
                        parts = text.split(":", 1)
                        k = parts[0].strip()
                        v = parts[1].strip()
                        if len(k) < 50 and v:
                            specifications[k] = v

            if specifications:
                product.specifications = specifications

        # 2. Parse description if empty
        if not product.description:
            desc_parts = []
            header_el = soup.find(class_=re.compile(r"trimName|product-title|model-name|vehicle-name", re.I)) or soup.find("h1")
            if header_el:
                curr = header_el.next_sibling
                count = 0
                while curr and count < 15:
                    if hasattr(curr, "name") and curr.name in ["p", "div"]:
                        txt = curr.get_text().strip()
                        if len(txt.split()) > 6 and not any(term in txt.lower() for term in ["cookie", "javascript", "copyright", "all rights reserved"]):
                            desc_parts.append(txt)
                            if len(desc_parts) >= 2:
                                break
                    curr = curr.next_sibling
                    count += 1
            if not desc_parts:
                meta_desc = soup.find("meta", attrs={"name": re.compile(r"description", re.I)})
                if meta_desc and meta_desc.get("content"):
                    desc_parts.append(meta_desc.get("content").strip())
            if desc_parts:
                product.description = " ".join(desc_parts)
