"""
agents/planner_agent.py

ADK Planner Agent — the SOLE reasoning engine of the autonomous-ai-scraper.

This agent:
- Accepts natural-language scraping requests from the user
- Plans the full MCP workflow
- Orchestrates all MCPs via tool calls
- Switches LLM providers automatically on quota/rate-limit/timeout
- NEVER performs scraping, extraction, or storage logic directly

ADK Architecture:
- Primary LLM: Gemini (gemini-2.5-flash)
- Fallback 1: Groq (llama-3.3-70b-versatile)
- Fallback 2: OpenRouter (qwen/qwen3-8b via OpenAI-compatible API)
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit, urljoin
from bs4 import BeautifulSoup


import google.generativeai as genai
from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import FunctionTool
from groq import AsyncGroq
from openai import AsyncOpenAI

from mcps.classification.classification_mcp import ClassificationMCP
from mcps.crawler.crawler_mcp import CrawlerMCP
from mcps.discovery.discovery_mcp import DiscoveryMCP
from mcps.execution.execution_mcp import ExecutionMCP
from mcps.extraction.extraction_mcp import ExtractionMCP
from mcps.knowledge.knowledge_mcp import KnowledgeMCP
from mcps.storage.storage_mcp import StorageMCP
from mcps.validation.validation_mcp import ValidationMCP
from shared.models import (
    ClassifiedURL,
    CrawlStatistics,
    CrawlTask,
    WebsiteProfile,
)
from shared.models.classified_url import normalize_page_type
from shared.utils.config import Config, get_config
from shared.utils.logging import get_logger

logger = get_logger(__name__)

APP_NAME = "autonomous-ai-scraper"
USER_ID = "planner-user"
SESSION_ID = "crawl-session"


# ─────────────────────────────────────────────────────────────────────────────
# Tool wrapper functions (ADK tools must be plain async functions)
# ─────────────────────────────────────────────────────────────────────────────

_discovery_mcp: DiscoveryMCP | None = None
_classification_mcp: ClassificationMCP | None = None
_crawler_mcp: CrawlerMCP | None = None
_execution_mcp: ExecutionMCP | None = None
_extraction_mcp: ExtractionMCP | None = None
_validation_mcp: ValidationMCP | None = None
_storage_mcp: StorageMCP | None = None
_knowledge_mcp: KnowledgeMCP | None = None
_crawl_task: CrawlTask | None = None
_stats: CrawlStatistics | None = None
_config: Config | None = None


def _get_mcps() -> tuple[
    DiscoveryMCP,
    ClassificationMCP,
    CrawlerMCP | None,
    ExecutionMCP,
    ExtractionMCP,
    ValidationMCP,
    StorageMCP,
    KnowledgeMCP,
]:
    assert all([
        _discovery_mcp, _classification_mcp,
        _execution_mcp, _extraction_mcp, _validation_mcp,
        _storage_mcp, _knowledge_mcp,
    ]), "MCPs not initialised — call init_mcps() first"
    return (  # type: ignore[return-value]
        _discovery_mcp, _classification_mcp, _crawler_mcp,
        _execution_mcp, _extraction_mcp, _validation_mcp,
        _storage_mcp, _knowledge_mcp,
    )


async def tool_discover(seed_url: str, max_pages: int = 100) -> str:
    """Discover all URLs on a website starting from seed_url.

    Fetches robots.txt, parses sitemaps, and extracts navigation links.
    Returns a JSON summary of discovered URLs and website profile.

    Args:
        seed_url: The starting URL for discovery (e.g. 'https://example.com').
        max_pages: Maximum number of pages to include in the crawl budget.

    Returns:
        JSON string with keys: profile_domain, urls_discovered, product_patterns,
        category_patterns, preferred_fetch_method.
    """
    global _crawl_task, _stats, _crawler_mcp

    discovery, *_ = _get_mcps()[:1]
    config = get_config()

    domain = urlsplit(seed_url).netloc
    task = CrawlTask(
        seed_url=seed_url,
        domain=domain,
        max_pages=max_pages,
    )
    _crawl_task = task
    _stats = CrawlStatistics(task_id=task.task_id, domain=domain)

    # Reinitialise CrawlerMCP with the real task now that we know the target site
    from mcps.crawler.crawler_mcp import CrawlerMCP as _CrawlerMCP
    _crawler_mcp = _CrawlerMCP(task=task, config=config)

    logger.info("tool_discover called", seed_url=seed_url, max_pages=max_pages)

    result = await discovery.discover(task)

    # Persist profile to Knowledge MCP
    _, _, _, _, _, _, _, knowledge = _get_mcps()
    await knowledge.save_profile(result.profile)

    return json.dumps({
        "profile_domain": result.profile.domain,
        "urls_discovered": len(result.urls),
        "sample_urls": result.urls[:10],
        "product_patterns": result.profile.product_url_patterns,
        "category_patterns": result.profile.category_url_patterns,
        "preferred_fetch_method": result.profile.preferred_fetch_method,
        "robots_disallow_count": len(result.profile.robots_disallow),
    })


async def tool_classify_urls(urls_json: str) -> str:
    """Classify a list of URLs into page types (product, category, pagination, unknown).

    Args:
        urls_json: JSON array of URL strings to classify.

    Returns:
        JSON string with list of {url, page_type, confidence, priority}.
    """
    _, classification, *_ = _get_mcps()[:2]
    _, _, _, _, _, _, _, knowledge = _get_mcps()

    urls: list[str] = json.loads(urls_json)
    if not urls:
        return json.dumps([])

    # Prune urls list to maximum 20 to prevent token limits truncation and JSON parsing crashes
    if len(urls) > 20:
        urls = urls[:20]

    # Get profile for domain context
    domain = urlsplit(urls[0]).netloc
    profile = await knowledge.get_profile(domain) or WebsiteProfile(
        domain=domain, seed_url=urls[0]
    )

    _, _, _, execution_mcp, *_ = _get_mcps()[:4]
    classified = await classification.classify(urls, profile, execution_mcp)

    return json.dumps([
        {
            "url": c.url,
            "page_type": c.page_type,
            "confidence": c.confidence,
            "priority": c.priority,
        }
        for c in classified
    ])


async def tool_enqueue_urls(classified_urls_json: str) -> str:
    """Add classified URLs to the crawler queue.

    Args:
        classified_urls_json: JSON array of classified URL objects from tool_classify_urls.

    Returns:
        JSON with count of URLs enqueued and current queue stats.
    """
    _, _, crawler, *_ = _get_mcps()[:3]

    data: list[dict] = json.loads(classified_urls_json)
    classified = [
        ClassifiedURL(
            url=d["url"],
            page_type=d["page_type"],
            confidence=d["confidence"],
            priority=d["priority"],
        )
        for d in data
    ]
    await crawler.enqueue(classified)
    stats = crawler.stats()
    return json.dumps({"enqueued": len(classified), "queue_stats": stats})


async def tool_get_next_batch(batch_size: int = 5) -> str:
    """Get the next batch of URLs to process from the crawler queue.

    Args:
        batch_size: Number of URLs to fetch (default 5).

    Returns:
        JSON array of URL objects with page_type and priority, or QUEUE_EMPTY message.
    """
    _, _, crawler, *_ = _get_mcps()[:3]
    batch = await crawler.next_batch(batch_size)
    if not batch:
        return "QUEUE_EMPTY: No more URLs to process. Please call the final success response now."
    return json.dumps([
        {"url": c.url, "page_type": c.page_type, "priority": c.priority}
        for c in batch
    ])


async def tool_fetch_and_extract(url: str, page_type: str = "product") -> str:
    """Fetch a URL and extract product data from it.

    This tool fetches the page (HTTP or Playwright as needed), then runs
    the 5-stage extraction pipeline. Use only for product pages.

    Args:
        url: The URL to fetch and extract from.
        page_type: Expected page type ('product' recommended).

    Returns:
        JSON with extraction success, confidence, method, and key product fields.
    """
    global _stats

    _, _, _, execution, extraction, _, _, knowledge = _get_mcps()

    domain = urlsplit(url).netloc
    profile = await knowledge.get_profile(domain) or WebsiteProfile(
        domain=domain, seed_url=url
    )

    # Fetch
    fetch_result = await execution.smart_fetch(url, profile)
    if _stats:
        _stats.total_fetched += 1
        if fetch_result.fetch_method == "playwright":
            _stats.playwright_fetches += 1
        else:
            _stats.http_fetches += 1
        if fetch_result.from_cache:
            _stats.cache_hits += 1

    if not fetch_result.success or not fetch_result.html:
        if _stats:
            _stats.total_errors += 1
        return json.dumps({
            "success": False,
            "url": url,
            "error": fetch_result.error.message if fetch_result.error else "Fetch failed",
        })

    # Extract
    extraction_result = await extraction.extract(fetch_result.html, profile, url=url)

    return json.dumps({
        "success": extraction_result.success,
        "url": url,
        "confidence": extraction_result.confidence,
        "method": extraction_result.method,
        "title": extraction_result.product.title if extraction_result.product else None,
        "price": extraction_result.product.price if extraction_result.product else None,
        "currency": extraction_result.product.currency if extraction_result.product else None,
        "brand": extraction_result.product.brand if extraction_result.product else None,
        "sku": extraction_result.product.sku if extraction_result.product else None,
        "availability": extraction_result.product.availability if extraction_result.product else None,
        "warnings": extraction_result.warnings,
    })


async def tool_validate_and_store(url: str) -> str:
    """Validate the last extracted product from a URL and store it if valid.

    Run tool_fetch_and_extract first, then call this to validate and persist.

    Args:
        url: The URL of the product page that was previously extracted.

    Returns:
        JSON with verdict (PASS/WARN/FAIL), quality_score, and storage result.
    """
    global _stats

    _, _, crawler, execution, extraction, validation, storage, knowledge = _get_mcps()

    domain = urlsplit(url).netloc
    profile = await knowledge.get_profile(domain) or WebsiteProfile(
        domain=domain, seed_url=url
    )

    # Re-fetch and extract (in a real pipeline the Planner stores state between calls)
    fetch_result = await execution.smart_fetch(url, profile)
    if not fetch_result.success or not fetch_result.html:
        await crawler.mark_failed(url, "Fetch failed on validate step")
        return json.dumps({"success": False, "url": url, "error": "Fetch failed"})

    extraction_result = await extraction.extract(fetch_result.html, profile, url=url)
    validation_result = await validation.validate(extraction_result)

    if _stats:
        _stats.total_products_extracted += 1

    stored = False
    if validation_result.passed and extraction_result.product:
        write_result = await storage.write(extraction_result.product, validation_result)
        stored = write_result.success
        if stored:
            if _stats:
                _stats.total_products_passed += 1
            await knowledge.record_extraction_success(
                domain, profile.selector_version, extraction_result.method
            )
        await crawler.mark_completed(url)
    else:
        if _stats:
            _stats.total_products_failed += 1
        await crawler.mark_failed(url, str(validation_result.errors))
        await knowledge.record_extraction_failure(domain, profile.selector_version)

    return json.dumps({
        "url": url,
        "verdict": validation_result.verdict,
        "quality_score": validation_result.quality_score,
        "stored": stored,
        "errors": validation_result.errors,
        "warnings": validation_result.warnings,
        "is_duplicate": validation_result.is_duplicate,
    })


async def tool_checkpoint() -> str:
    """Save the current crawler queue state to a checkpoint file.

    Call this periodically during long crawls to enable resume on interruption.

    Returns:
        JSON with checkpoint path and queue statistics.
    """
    _, _, crawler, *_ = _get_mcps()[:3]
    stats = {}
    if crawler:
        await crawler.checkpoint()
        stats = crawler.stats()
    return json.dumps({"checkpointed": bool(crawler), "queue_stats": stats})


async def tool_get_crawl_stats() -> str:
    """Get real-time statistics for the current crawl session.

    Returns:
        JSON with counts for fetched, extracted, passed, failed, and error metrics.
    """
    _, _, crawler, *_ = _get_mcps()[:3]
    queue_stats = crawler.stats() if crawler else {}

    crawl_stats = {}
    if _stats:
        crawl_stats = {
            "total_fetched": _stats.total_fetched,
            "total_products_extracted": _stats.total_products_extracted,
            "total_products_passed": _stats.total_products_passed,
            "total_products_failed": _stats.total_products_failed,
            "total_errors": _stats.total_errors,
            "http_fetches": _stats.http_fetches,
            "playwright_fetches": _stats.playwright_fetches,
            "cache_hits": _stats.cache_hits,
            "success_rate": _stats.success_rate,
        }

    return json.dumps({**queue_stats, **crawl_stats})


async def tool_get_domain_recommendations(domain: str) -> str:
    """Get Knowledge MCP recommendations for scraping a specific domain.

    Use this before starting a crawl to check if we have prior knowledge.

    Args:
        domain: The domain to get recommendations for (e.g. 'example.com').

    Returns:
        JSON with preferred_fetch_method, skip_discovery, selector_version,
        rollback_selector_version recommendations.
    """
    norm_domain = domain.lower().replace("www.", "")
    _, _, _, _, _, _, _, knowledge = _get_mcps()
    recs = await knowledge.get_recommendations(norm_domain)
    return json.dumps({
        "preferred_fetch_method": recs.preferred_fetch_method,
        "recommended_concurrency": recs.recommended_concurrency,
        "selector_version": recs.selector_version,
        "skip_discovery": recs.skip_discovery,
        "rollback_selector_version": recs.rollback_selector_version,
        "notes": recs.notes,
    })


async def tool_finalize_crawl() -> str:
    """Finalize the crawl: flush storage, update knowledge profile, return summary.

    Call this when the crawl is complete or the budget is exhausted.

    Returns:
        JSON summary of the completed crawl.
    """
    global _stats, _crawl_task

    _, _, crawler, _, _, _, storage, knowledge = _get_mcps()

    await storage.flush()
    await storage.close()

    queue_stats = crawler.stats()

    if _stats and _crawl_task:
        _stats.completed_at = datetime.utcnow()
        domain = _crawl_task.domain
        profile = await knowledge.get_profile(domain)
        if profile:
            await knowledge.update_from_crawl(_stats, profile)

    return json.dumps({
        "crawl_complete": True,
        "queue_stats": queue_stats,
        "crawl_stats": {
            "total_products_passed": _stats.total_products_passed if _stats else 0,
            "total_fetched": _stats.total_fetched if _stats else 0,
            "elapsed_seconds": _stats.elapsed_seconds if _stats else None,
        },
        "outputs": "Check outputs/ directory for CSV, JSON, and SQLite files",
    })


async def tool_extract_urls_from_page(url: str) -> str:
    """Fetch any page (e.g. a category listing page) and extract all hyperlinks found on it.

    Use this when you have a category URL and need to find the child product URLs on that page.

    Args:
        url: The category or listing page URL.

    Returns:
        JSON string containing the list of absolute URLs found on the page.
    """
    _, _, _, execution, _, _, _, knowledge = _get_mcps()
    domain = urlsplit(url).netloc
    profile = await knowledge.get_profile(domain) or WebsiteProfile(
        domain=domain, seed_url=url
    )

    fetch_result = await execution.smart_fetch(url, profile)
    if not fetch_result.success or not fetch_result.html:
        return json.dumps([])

    soup = BeautifulSoup(fetch_result.html, "html.parser")
    found_urls = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        # Convert to absolute URL
        absolute_url = urljoin(url, href)
        if urlsplit(absolute_url).netloc == domain:
            found_urls.append(absolute_url)

    # Deduplicate while preserving order
    unique_urls = list(dict.fromkeys(found_urls))
    return json.dumps(unique_urls)


async def tool_extract_navigation_routes(domain: str) -> str:
    """Parse raw navigation markdown content to extract potential catalog/category routes.

    If navigation markdown is missing, it dynamically runs a mini-discovery fetch
    to build it on the fly.

    Args:
        domain: The website domain name (e.g. 'example.com').

    Returns:
        JSON string listing category/catalog URLs.
    """
    norm_domain = domain.lower().replace("www.", "")
    discovery, classification, _, _, _, _, _, knowledge = _get_mcps()
    profile = await knowledge.get_profile(norm_domain)

    if not profile or not profile.navigation_markdown:
        logger.info("Navigation markdown missing; performing dynamic menu extraction fetch", domain=norm_domain)
        from shared.models import CrawlTask as _CrawlTask
        seed_url = f"https://{norm_domain}" if not profile else profile.seed_url
        task = _CrawlTask(seed_url=seed_url, domain=norm_domain, max_pages=10)

        # Run discovery to populate profile and navigation layouts
        res = await discovery.discover(task)
        profile = res.profile
        await knowledge.save_profile(profile)


    urls = classification.extract_navigation_routes(profile)
    return json.dumps(urls)


# ─────────────────────────────────────────────────────────────────────────────
# LLM Provider Fallback Chain
# ─────────────────────────────────────────────────────────────────────────────
from shared.utils.llm_utils import llm_with_fallback



# ─────────────────────────────────────────────────────────────────────────────
# MCP Initialisation
# ─────────────────────────────────────────────────────────────────────────────

def _sync_to_sys_modules() -> None:
    import sys
    current_module = sys.modules[__name__]
    for name, module in list(sys.modules.items()):
        if name.endswith("planner_agent") and module is not current_module:
            try:
                module._discovery_mcp = _discovery_mcp
                module._classification_mcp = _classification_mcp
                module._crawler_mcp = _crawler_mcp
                module._execution_mcp = _execution_mcp
                module._extraction_mcp = _extraction_mcp
                module._validation_mcp = _validation_mcp
                module._storage_mcp = _storage_mcp
                module._knowledge_mcp = _knowledge_mcp
                module._crawl_task = _crawl_task
                module._stats = _stats
                module._config = _config
            except AttributeError:
                pass


async def init_mcps(config: Config) -> None:
    """Initialise all MCP singletons.

    Args:
        config: Loaded application configuration.
    """
    global _discovery_mcp, _classification_mcp, _crawler_mcp, _execution_mcp, _extraction_mcp, _validation_mcp, _storage_mcp, _knowledge_mcp, _config
    _config = config

    _knowledge_mcp = KnowledgeMCP(config.knowledge.db_path)
    await _knowledge_mcp.init()

    _execution_mcp = ExecutionMCP(config)
    _discovery_mcp = DiscoveryMCP(config, playwright_mcp=_execution_mcp.playwright)
    _classification_mcp = ClassificationMCP()
    _extraction_mcp = ExtractionMCP(config)
    _validation_mcp = ValidationMCP()
    _storage_mcp = StorageMCP(config)

    logger.info("All MCPs initialised")
    _sync_to_sys_modules()


async def teardown_mcps() -> None:
    """Cleanly shut down all MCP resources."""
    global _discovery_mcp, _classification_mcp, _crawler_mcp, _execution_mcp, _extraction_mcp, _validation_mcp, _storage_mcp, _knowledge_mcp
    if _execution_mcp:
        await _execution_mcp.close()
    if _storage_mcp:
        await _storage_mcp.close()
    if _knowledge_mcp:
        await _knowledge_mcp.close()
    
    _discovery_mcp = None
    _classification_mcp = None
    _crawler_mcp = None
    _execution_mcp = None
    _extraction_mcp = None
    _validation_mcp = None
    _storage_mcp = None
    _knowledge_mcp = None
    logger.info("All MCPs shut down")
    _sync_to_sys_modules()


# ─────────────────────────────────────────────────────────────────────────────
# ADK Agent Setup
# ─────────────────────────────────────────────────────────────────────────────

PLANNER_SYSTEM_PROMPT = """You are an autonomous AI web scraping planner. Your job is to:

1. Understand the user's scraping request (what site, what data, how many products).
2. Check domain recommendations from Knowledge MCP to reuse prior knowledge.
3. Use Discovery MCP to find all URLs on the site.
4. Use Classification MCP to identify product pages.
5. Use Crawler MCP to manage the URL queue.
6. For each product URL batch: use fetch_and_extract, then validate_and_store.
7. Checkpoint periodically (every 50 URLs).
8. When done: call finalize_crawl and report a summary to the user.

Rules you must follow:
- Process URLs in batches of 5-10 for efficiency.
- Only call fetch_and_extract on product-type pages.
- Call tool_checkpoint every 50 products processed.
- Always call tool_finalize_crawl when the queue is empty or budget is reached.
- Report final statistics: products found, products stored, success rate.
- If a domain has been crawled before (skip_discovery=true from recommendations),
  skip discovery and go directly to classification.

You have access to these tools:
- tool_discover: Discover URLs from a website
- tool_classify_urls: Classify URLs into page types
- tool_enqueue_urls: Add URLs to the crawler queue
- tool_get_next_batch: Get next URLs to process
- tool_fetch_and_extract: Fetch a URL and extract product data
- tool_validate_and_store: Validate and persist extracted product
- tool_checkpoint: Save queue state for resume
- tool_get_crawl_stats: Get real-time crawl statistics
- tool_get_domain_recommendations: Check prior knowledge for a domain
- tool_finalize_crawl: Complete the crawl and generate summary
"""


def build_adk_agent(config: Config) -> Agent:
    """Build and return the ADK Planner Agent with all MCP tools registered.

    Args:
        config: Loaded application configuration.

    Returns:
        Configured ADK Agent instance.
    """
    tools = [
        FunctionTool(tool_discover),
        FunctionTool(tool_classify_urls),
        FunctionTool(tool_enqueue_urls),
        FunctionTool(tool_get_next_batch),
        FunctionTool(tool_fetch_and_extract),
        FunctionTool(tool_validate_and_store),
        FunctionTool(tool_checkpoint),
        FunctionTool(tool_get_crawl_stats),
        FunctionTool(tool_get_domain_recommendations),
        FunctionTool(tool_finalize_crawl),
        FunctionTool(tool_extract_navigation_routes),
    ]

    agent = Agent(
        name="autonomous_scraper_planner",
        model=f"google/{config.llm.gemini_model}",
        description="Autonomous web scraping planner that orchestrates MCPs",
        instruction=PLANNER_SYSTEM_PROMPT,
        tools=tools,
    )

    logger.info(
        "ADK Planner Agent built",
        model=config.llm.gemini_model,
        tool_count=len(tools),
    )
    return agent


async def run_scraping_task(
    prompt: str,
    config: Config,
) -> str:
    """Run a scraping task from a natural-language prompt.

    Args:
        prompt: Natural-language scraping instruction from the user.
        config: Loaded application configuration.

    Returns:
        Final response text from the planner agent.
    """
    await init_mcps(config)

    try:
        agent = build_adk_agent(config)
        session_service = InMemorySessionService()

        await session_service.create_session(
            app_name=APP_NAME,
            user_id=USER_ID,
            session_id=SESSION_ID,
        )

        runner = Runner(
            agent=agent,
            app_name=APP_NAME,
            session_service=session_service,
        )

        from google.adk.types import Content, Part

        final_response = ""
        async for event in runner.run_async(
            user_id=USER_ID,
            session_id=SESSION_ID,
            new_message=Content(parts=[Part(text=prompt)]),
        ):
            if event.is_final_response() and event.content and event.content.parts:
                final_response = "".join(
                    p.text for p in event.content.parts if hasattr(p, "text")
                )

        return final_response
    finally:
        await teardown_mcps()


# Expose the crawler MCP setter for main.py to inject after task creation
def set_crawler_mcp(task: CrawlTask, config: Config) -> None:
    """Inject a CrawlerMCP for the given task (called by main.py after task creation)."""
    global _crawler_mcp
    _crawler_mcp = CrawlerMCP(task=task, config=config)
    _sync_to_sys_modules()
