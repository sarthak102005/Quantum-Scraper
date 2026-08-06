"""
agent.py

Declarative ADK Agent definition for auto-discovery by the 'adk web' command.
Imports all MCP tools and exposes the scraping planner agent.
"""

from __future__ import annotations

import json
import asyncio
from urllib.parse import urlsplit
from google.adk import agent, tool

from agents.planner_agent import (
    tool_discover,
    tool_classify_urls,
    tool_enqueue_urls,
    tool_get_next_batch,
    tool_fetch_and_extract,
    tool_validate_and_store,
    tool_checkpoint,
    tool_get_crawl_stats,
    tool_get_domain_recommendations,
    tool_finalize_crawl,
    init_mcps,
)
from shared.utils.config import get_config

# Global lock to ensure MCPs are initialized exactly once upon the first tool execution
_initialized = False
_init_lock = asyncio.Lock()

async def ensure_initialized():
    global _initialized
    if not _initialized:
        async with _init_lock:
            if not _initialized:
                config = get_config()
                await init_mcps(config)
                _initialized = True

# Register all tools with ADK decorators
@tool
async def discover(seed_url: str, max_pages: int = 100) -> str:
    """Discover all URLs on a website starting from seed_url.
    Returns a JSON dict summarizing discovered URLs.
    """
    await ensure_initialized()
    return await tool_discover(seed_url, max_pages)


@tool
async def classify_urls(urls_json: str) -> str:
    """Classify a list of URLs into page types using heuristics.
    Expects a JSON array of URL strings.
    """
    await ensure_initialized()
    return await tool_classify_urls(urls_json)


@tool
async def enqueue_urls(classified_urls_json: str) -> str:
    """Add classified URLs to the crawler queue.
    Expects a JSON array of classified URL objects.
    """
    await ensure_initialized()
    return await tool_enqueue_urls(classified_urls_json)


@tool
async def get_next_batch(batch_size: int = 5) -> str:
    """Get the next batch of URLs to process from the crawler queue."""
    await ensure_initialized()
    return await tool_get_next_batch(batch_size)


@tool
async def fetch_and_extract(url: str, page_type: str = "product") -> str:
    """Fetch a URL and extract product data from it."""
    await ensure_initialized()
    return await tool_fetch_and_extract(url, page_type)


@tool
async def validate_and_store(url: str) -> str:
    """Validate the last extracted product from a URL and store it if valid.
    Run fetch_and_extract first on the URL before calling this.
    """
    await ensure_initialized()
    return await tool_validate_and_store(url)


@tool
async def save_checkpoint() -> str:
    """Save the current crawler queue state to a checkpoint file."""
    await ensure_initialized()
    return await tool_checkpoint()


@tool
async def get_crawl_stats() -> str:
    """Get real-time statistics for the current crawl session."""
    await ensure_initialized()
    return await tool_get_crawl_stats()


@tool
async def get_domain_recommendations(domain: str) -> str:
    """Get Knowledge MCP recommendations for scraping a specific domain."""
    await ensure_initialized()
    return await tool_get_domain_recommendations(domain)


@tool
async def finalize_crawl() -> str:
    """Finalize the crawl: flush storage, update knowledge profile, return summary."""
    await ensure_initialized()
    return await tool_finalize_crawl()


# Get Gemini model configuration for the decorator
config = get_config()

# Define the agent matching your Gemini Model config
@agent(
    name="autonomous_scraper_planner",
    description="Autonomous web scraping planner that orchestrates MCPs",
    model=f"google/{config.llm.gemini_model}",
    instruction="""You are an autonomous AI e-commerce scraping planner.

To scrape any website with 100% accuracy, you must locate products by navigating its menu/navbar hierarchy (e.g., Header 1 > Header 2 > ... > Product URL) rather than relying on URL regex patterns.

When you receive a scraping request, execute this workflow:
1. Call `get_domain_recommendations` to check prior knowledge and details about the domain.
2. Call `discover` to fetch the homepage, build the navigation markdown menu structure, and extract sitemaps.
3. Examine the returned navigation markdown. Identify category/subcategory hierarchy paths (e.g., "Products > Machines" or "Products > Lawn Mowing").
4. If a category page requires interaction (like clicking "Load More" or scrolling), use Playwright MCP options.
5. Classify the discovered URLs using `classify_urls` (which uses a weighted scoring engine: JSON-LD: +60, Price: +20, Cart: +20, SKU/Model: +15).
6. Enqueue the URLs using `enqueue_urls`.
7. Retrieve batches of URLs using `get_next_batch`.
8. For each product URL:
   - Call `fetch_and_extract` to run the 5-stage extraction pipeline.
   - Call `validate_and_store` to validate the extracted product and save it.
9. Finalize the crawl using `finalize_crawl` when done, then present a summary to the user.
"""
)
class AutonomousScraperPlanner:
    """Scraper Planner Agent exposed to ADK Web UI."""
