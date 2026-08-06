"""
mcps/classification/classification_mcp.py

Classification MCP — processes a list of URLs and classifies their target
page types using heuristics and optional HTML snippet inspection.
"""

from __future__ import annotations
from typing import Any
import asyncio
import re
import json

from shared.models.classified_url import ClassifiedURL, PageType, normalize_page_type
from shared.models.website_profile import WebsiteProfile
from shared.utils.logging import get_logger
from shared.utils.config import get_config
from shared.utils.llm_utils import llm_with_fallback
from mcps.classification.heuristics import classify_url
from mcps.knowledge.knowledge_mcp import KnowledgeMCP

logger = get_logger(__name__)


class ClassificationMCP:
    """Classifies candidate URLs for a target profile."""

    def __init__(self, knowledge_mcp: KnowledgeMCP | None = None) -> None:
        config = get_config()
        self.knowledge_mcp = knowledge_mcp or KnowledgeMCP(config.knowledge.db_path)

    async def classify(
        self,
        urls: list[str],
        profile: WebsiteProfile,
        execution_mcp: Any | None = None,
    ) -> list[ClassifiedURL]:
        """Classify a list of URLs using a multi-stage Page Type Classification Engine.

        Args:
            urls: List of URL strings.
            profile: Contextual WebsiteProfile.
            execution_mcp: Optional ExecutionMCP instance to fetch HTML snippets.

        Returns:
            List of ClassifiedURL models.
        """
        logger.info("Classifying URLs using multi-stage engine", count=len(urls))
        results: list[ClassifiedURL] = []
        config = get_config()

        try:
            await self.knowledge_mcp.init()

            for url in urls:
                # Stage 1: URL-only heuristics
                ptype, confidence, signals = classify_url(url, profile=profile)

                # Stage 2: Escalate to Playwright snippet fetch for medium/low confidence or unknown
                if execution_mcp and (ptype == "UNKNOWN" or confidence < 0.85):
                    logger.info("Deterministic score in uncertain band; escalating to Playwright", url=url, initial_type=ptype, confidence=confidence)
                    try:
                        res = await execution_mcp.smart_fetch(url, profile)
                        if res.success and res.html:
                            # Re-run deterministic classifier with HTML
                            html_snippet = res.html[:150000]
                            new_ptype, new_confidence, new_signals = classify_url(
                                url, html_snippet=html_snippet, profile=profile
                            )
                            if new_ptype != "UNKNOWN":
                                ptype, confidence, signals = new_ptype, new_confidence, new_signals

                            # Stage 3: LLM Fallback if still uncertain
                            if config.llm.extraction_fallback_enabled and (ptype == "UNKNOWN" or confidence < 0.85):
                                logger.info("Classification remains uncertain; running LLM fallback", url=url, type=ptype, confidence=confidence)
                                # Extract clean text content to fit inside token limits
                                text_content = re.sub(r"<script.*?</script>", "", res.html, flags=re.DOTALL)
                                text_content = re.sub(r"<style.*?</style>", "", text_content, flags=re.DOTALL)
                                text_content = re.sub(r"<[^>]+>", " ", text_content)
                                text_content = " ".join(text_content.split())
                                truncated_text = text_content[:4000]

                                prompt = f"""
You are an expert page classification assistant. Your task is to classify the page type of the URL based on the URL and text content.
Classify the page into one of the following exact types:
- PRODUCT: Represents one unique product model/detail page.
- CATEGORY: Product grid/lists, search results with pagination.
- PRODUCT_FAMILY: Groups multiple related products/models, comparison tables.
- SERVICE: Financing, leasing, warranty, rental.
- SUPPORT: Support, repair, parts.
- DOCUMENTATION: Manuals, brochures, datasheets.
- BLOG: Blog posts, articles.
- NEWS: News, announcements.
- LANDING_PAGE: Home page, landing page.
- DEALER: Dealer locator, find a store.
- SEARCH_RESULTS: Search results page.
- ACCOUNT: Login, register, cart, checkout.
- UNKNOWN: Default fallback.

Return ONLY a valid JSON object matching the schema below. Do not include markdown codeblocks or conversational text.

Output JSON format:
{{
  "page_type": "PRODUCT",
  "confidence": 0.95,
  "reasoning": "Reasoning for this choice"
}}

URL to classify: {url}
Fired signals: {signals}

Web page content snippet:
-----------------------------
{truncated_text}
-----------------------------
"""
                                try:
                                    resp_text = await llm_with_fallback(prompt, config)
                                    match = re.search(r"\{.*?\}", resp_text, re.DOTALL)
                                    if match:
                                        data = json.loads(match.group(0))
                                        llm_type = normalize_page_type(data.get("page_type"))
                                        llm_conf = float(data.get("confidence", 0.70))
                                        llm_reason = data.get("reasoning", "")

                                        ptype = llm_type
                                        confidence = llm_conf
                                        signals.append(f"LLM Classification: {llm_type} ({llm_reason})")
                                except Exception as e:
                                    logger.error("LLM fallback classification failed", url=url, error=str(e))
                    except Exception as e:
                        logger.error("Playwright snippet escalation failed", url=url, error=str(e))

                # Map priorities
                priority = 0
                if ptype == "PRODUCT":
                    priority = 3
                elif ptype == "PRODUCT_FAMILY":
                    priority = 2
                elif ptype in ("CATEGORY", "SEARCH_RESULTS"):
                    priority = 1

                classified = ClassifiedURL(
                    url=url,
                    page_type=ptype,
                    confidence=confidence,
                    signals_fired=signals,
                    priority=priority,
                )
                results.append(classified)

                # Persist classification event in Knowledge store
                await self.knowledge_mcp.record_classification(
                    domain=profile.domain,
                    url=url,
                    confidence=confidence,
                    is_product=(ptype == "PRODUCT"),
                    signals=signals,
                )

        finally:
            await self.knowledge_mcp.close()

        logger.info("URL classification complete", total_classified=len(results))
        return results

    def extract_navigation_routes(self, profile: WebsiteProfile) -> list[str]:
        """Parse raw navigation markdown content to extract potential catalog/category routes."""
        if not profile.navigation_markdown:
            return []
        
        # Match markdown links: [text](url)
        matches = re.findall(r"\[([^\]]+)\]\((https?://[^\)]+)\)", profile.navigation_markdown)
        urls = [url for text, url in matches]
        logger.info("Extracted category navigation links", count=len(urls))
        return urls
