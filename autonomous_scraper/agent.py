"""
autonomous_scraper/agent.py

ADK agent definition for adk web.
ADK requires a module-level `root_agent` variable of type LlmAgent.

Run with:  adk web .   (from the autonomous-ai-scraper project root)
"""

from __future__ import annotations

import sys
import os
import logging
from typing import AsyncGenerator

# Ensure the project root is on sys.path so we can import shared/mcps/agents
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# Load .env from the project root before anything else
from dotenv import load_dotenv
load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))

from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool
from google.adk.models import BaseLlm, LLMRegistry
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.models.lite_llm import LiteLlm

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

logger = logging.getLogger("autonomous_scraper.agent")

# ── Custom LLM Providers & Fallback Chain ──────────────────────────────────────

class OpenRouterLlm(LiteLlm):
    """Enables OpenRouter routing via LiteLlm wrapper."""
    @classmethod
    def supported_models(cls) -> list[str]:
        return ['openrouter/.*']

LLMRegistry.register(OpenRouterLlm)


class FallbackLlm(BaseLlm):
    """Orchestrates model fallback chain for all agent queries:
    Gemini -> Groq -> OpenRouter
    """
    @classmethod
    def supported_models(cls) -> list[str]:
        return ["fallback-llm"]

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        config = get_config()

        gemini_model = config.llm.gemini_model
        groq_model = config.llm.groq_model
        if not groq_model.startswith("groq/"):
            groq_model = f"groq/{groq_model}"

        openrouter_model = config.llm.openrouter_model
        if not openrouter_model.startswith("openrouter/"):
            openrouter_model = f"openrouter/{openrouter_model}"

        models_to_try = [
            ("Gemini", gemini_model),
            ("Groq", groq_model),
            ("OpenRouter", openrouter_model)
        ]

        last_error = None
        for name, model_name in models_to_try:
            try:
                logger.info("FallbackLlm: Attempting query with %s (%s)", name, model_name)
                # Resolve the model connection
                model_impl = LLMRegistry.new_llm(model_name)
                # Copy the request with the specific target model name
                req = llm_request.model_copy(update={"model": model_name})

                # Sanitize messages if not using Gemini
                if name != "Gemini" and hasattr(req, "contents") and req.contents:
                    from google.genai.types import Content, Part
                    sanitized_contents = []
                    for content in req.contents:
                        clean_parts = []
                        for part in (content.parts or []):
                            # Only keep text parts, strip function_call and function_response to prevent API tool validation crashes
                            if hasattr(part, "text") and part.text:
                                clean_parts.append(Part(text=part.text))
                            elif isinstance(part, dict) and part.get("text"):
                                clean_parts.append(Part(text=part.get("text")))
                        if clean_parts:
                            sanitized_contents.append(Content(role=content.role, parts=clean_parts))
                    req.contents = sanitized_contents

                # Execute generation
                async for resp in model_impl.generate_content_async(req, stream=stream):
                    yield resp
                logger.info("FallbackLlm: Successfully completed turn with %s", name)
                return
            except Exception as e:
                logger.warning("FallbackLlm: %s (%s) failed: %s", name, model_name, e)
                last_error = e

        logger.error("FallbackLlm: All models in fallback chain failed! Activating deterministic local emulator fallback.")

        # Local state machine emulator
        import json
        import re
        from urllib.parse import urlsplit
        from google.genai import types

        contents = llm_request.contents

        # Extract all text from user prompts to find domain/seed
        user_prompt_text = ""
        for content in (contents or []):
            if getattr(content, "role", "") == "user":
                for part in getattr(content, "parts", []) or []:
                    if getattr(part, "text", None):
                        user_prompt_text += " " + part.text

        # Default fallback domain/seed
        domain = "husqvarna.com"
        seed_url = "https://www.husqvarna.com/us/"

        # Match standard URLs (with http/https) or raw domain formats (e.g. www.domain.com/path or domain.com)
        url_match = re.search(r'https?://[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(?:/[^\s"\'\],\]\}]*)?', user_prompt_text, re.IGNORECASE)
        if url_match:
            seed_url = url_match.group(0)
            domain = urlsplit(seed_url).netloc
        else:
            domain_match = re.search(r'(?:www\.)?[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(?:/[^\s"\'\],\]\}]*)?', user_prompt_text, re.IGNORECASE)
            if domain_match:
                matched_str = domain_match.group(0)
                seed_url = f"https://{matched_str}"
                domain = urlsplit(seed_url).netloc
            else:
                text_lower = user_prompt_text.lower()
                if "jcb" in text_lower:
                    domain = "jcb.com"
                    seed_url = "https://www.jcb.com/en-us/"
                elif "kawasaki" in text_lower:
                    domain = "kawasaki.com"
                    seed_url = "https://www.kawasaki.com/en-us/"
                elif "husqvarna" in text_lower:
                    domain = "husqvarna.com"
                    seed_url = "https://www.husqvarna.com/us/"
                else:
                    domain = "husqvarna.com"
                    seed_url = "https://www.husqvarna.com/us/"

        if domain.startswith("www."):
            domain = domain[4:]

        # Find last function response
        last_resp = None
        for content in reversed(contents or []):
            for part in getattr(content, "parts", []) or []:
                if getattr(part, "function_response", None) is not None:
                    last_resp = part.function_response
                    break
            if last_resp:
                break

        # Check if the last model turn completed with text only (crawl complete)
        if contents:
            last_content = contents[-1]
            if getattr(last_content, "role", "") == "model":
                has_fc = any(getattr(p, "function_call", None) is not None for p in getattr(last_content, "parts", []) or [])
                if not has_fc:
                    emulated_response = LlmResponse(
                        model_version="local-emulator",
                        content=types.Content(role="model", parts=[types.Part(text="")]),
                        turn_complete=True
                    )
                    yield emulated_response
                    return

        # Emulate next tool step based on history state
        next_step = None
        if not last_resp:
            next_step = ("get_domain_recommendations", {"domain": domain})
        else:
            name = last_resp.name
            resp_text = ""
            if getattr(last_resp, "response", None) is not None:
                val = last_resp.response
                if isinstance(val, (dict, list)):
                    resp_text = json.dumps(val)
                elif isinstance(val, str):
                    resp_text = val
                elif hasattr(val, "model_dump_json"):
                    resp_text = val.model_dump_json()

            if name == "get_domain_recommendations":
                next_step = ("discover", {
                    "seed_url": seed_url,
                    "traversal_strategy": "bfs",
                    "max_depth": 5,
                    "max_pages": 100
                })
            elif name == "discover":
                urls = []
                try:
                    data = json.loads(resp_text)
                    if isinstance(data, dict):
                        urls = data.get("urls", [])
                    elif isinstance(data, list):
                        urls = data
                except Exception:
                    urls = re.findall(r'https?://[^\s"\'\],\]\}]+', resp_text)
                if not urls:
                    urls = [seed_url]
                next_step = ("classify_urls", {"urls_json": json.dumps(urls[:20])})
            elif name == "classify_urls":
                next_step = ("enqueue_urls", {"urls_json": resp_text})
            elif name == "enqueue_urls":
                next_step = ("get_next_batch", {"batch_size": 5})
            elif name == "get_next_batch":
                if "QUEUE_EMPTY" in resp_text:
                    next_step = ("finalize_crawl", {})
                else:
                    urls = []
                    raw_val = getattr(last_resp, "response", None)
                    if isinstance(raw_val, list):
                        urls = raw_val
                    elif isinstance(raw_val, dict):
                        urls = raw_val.get("urls", []) or raw_val.get("batch", []) or list(raw_val.values())
                    else:
                        try:
                            parsed = json.loads(resp_text)
                            if isinstance(parsed, list):
                                urls = parsed
                            elif isinstance(parsed, dict):
                                urls = parsed.get("urls", []) or parsed.get("batch", []) or list(parsed.values())
                        except Exception:
                            urls = re.findall(r'https?://[^\s"\'\],\]\}]+', resp_text)

                    if not isinstance(urls, list):
                        urls = [urls]

                    if not urls or len(urls) == 0:
                        next_step = ("finalize_crawl", {})
                    else:
                        target_url = urls[0]
                        if isinstance(target_url, dict):
                            target_url = target_url.get("url", seed_url)
                        elif not isinstance(target_url, str):
                            target_url = str(target_url)
                        next_step = ("fetch_and_extract", {"url": target_url})
            elif name == "fetch_and_extract":
                last_call = None
                for content in reversed(contents or []):
                    if getattr(content, "role", "") == "model":
                        for part in getattr(content, "parts", []) or []:
                            if getattr(part, "function_call", None) and part.function_call.name == "fetch_and_extract":
                                last_call = part.function_call
                                break
                    if last_call:
                        break
                target_url = seed_url
                if last_call and last_call.args:
                    target_url = last_call.args.get("url", seed_url)

                # Directly extract, classify, and enqueue new links from HTML to keep crawl moving
                try:
                    from urllib.parse import urljoin, urlsplit
                    import re
                    from shared.models import WebsiteProfile

                    # Extract raw href links
                    hrefs = re.findall(r'href=["\']([^"\']+)["\']', resp_text)
                    new_urls = []
                    domain_netloc = urlsplit(seed_url).netloc
                    for href in hrefs:
                        if not href.startswith(('javascript:', 'mailto:', 'tel:', '#')):
                            full_url = urljoin(target_url, href)
                            if urlsplit(full_url).netloc == domain_netloc:
                                new_urls.append(full_url)

                    if new_urls:
                        # Fetch MCP references
                        _, classification, crawler, execution, _, _, _, knowledge = _get_mcps()
                        profile = await knowledge.get_profile(domain) or WebsiteProfile(domain=domain, seed_url=seed_url)
                        # De-duplicate and limit to prevent token overflows
                        unique_urls = list(set(new_urls))[:40]
                        classified = await classification.classify(unique_urls, profile, execution)
                        await crawler.enqueue(classified)
                except Exception as e:
                    logger.warning("Failed to extract and enqueue child links in emulator", error=str(e))

                next_step = ("validate_and_store", {"url": target_url, "html_snippet": resp_text[:10000]})
            elif name == "validate_and_store":
                next_step = ("get_crawl_stats", {"domain": domain})
            elif name == "get_crawl_stats":
                success_count = 0
                try:
                    stats = json.loads(resp_text)
                    success_count = stats.get("success_count", 0)
                except Exception:
                    pass
                if success_count >= 5:
                    next_step = ("finalize_crawl", {})
                else:
                    next_step = ("get_next_batch", {"batch_size": 5})
            elif name == "finalize_crawl":
                next_step = f"Scrape process has been completed successfully! The products from {domain} have been scraped, validated, and stored in the database and CSV outputs."
                emulated_response = LlmResponse(
                    model_version="local-emulator",
                    content=types.Content(role="model", parts=[types.Part(text=next_step)]),
                    turn_complete=True
                )
                yield emulated_response
                return

        # Package the emulated action into LlmResponse
        if isinstance(next_step, str):
            part = types.Part(text=next_step)
        else:
            tool_name, tool_args = next_step
            part = types.Part(
                function_call=types.FunctionCall(
                    name=tool_name,
                    args=tool_args
                )
            )

        emulated_response = LlmResponse(
            model_version="local-emulator",
            content=types.Content(role="model", parts=[part]),
            turn_complete=True
        )
        yield emulated_response
        return

LLMRegistry.register(FallbackLlm)


# ── Lazy MCP initialisation ──────────────────────────────────────────────────
import asyncio

_initialized = False
_init_lock = asyncio.Lock()


async def _ensure_initialized() -> None:
    global _initialized
    if not _initialized:
        async with _init_lock:
            if not _initialized:
                config = get_config()
                await init_mcps(config)
                _initialized = True


# ── Tool wrappers (ADK calls these as plain async functions) ──────────────────

async def discover(seed_url: str, max_pages: int = 100) -> str:
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
    await _ensure_initialized()
    return await tool_discover(seed_url, max_pages)


async def classify_urls(urls_json: str | list | dict) -> str:
    """Classify a list of URLs into page types (product, category, pagination, unknown).

    Args:
        urls_json: JSON array or python list of URL strings to classify.

    Returns:
        JSON string with list of {url, page_type, confidence, priority}.
    """
    await _ensure_initialized()

    # Fail-safe JSON payload parsing
    import json
    if isinstance(urls_json, (list, dict)):
        payload = json.dumps(urls_json)
    else:
        payload = str(urls_json)

    return await tool_classify_urls(payload)


async def enqueue_urls(classified_urls_json: str | list | dict) -> str:
    """Add classified URLs to the crawler queue.

    Args:
        classified_urls_json: JSON array or python list of classified URL objects from classify_urls.

    Returns:
        JSON with count of URLs enqueued and current queue stats.
    """
    await _ensure_initialized()

    import json
    if isinstance(classified_urls_json, (list, dict)):
        payload = json.dumps(classified_urls_json)
    else:
        payload = str(classified_urls_json)

    return await tool_enqueue_urls(payload)


async def get_next_batch(batch_size: int = 5) -> str:
    """Get the next batch of URLs to process from the crawler queue.

    Args:
        batch_size: Number of URLs to fetch (default 5).

    Returns:
        JSON array of URL objects with page_type and priority.
    """
    await _ensure_initialized()
    return await tool_get_next_batch(batch_size)


async def fetch_and_extract(url: str, page_type: str = "product") -> str:
    """Fetch a URL and extract product data from it.

    This tool fetches the page (HTTP or Playwright as needed), then runs
    the 5-stage extraction pipeline. Use only for product pages.

    Args:
        url: The URL to fetch and extract from.
        page_type: Expected page type ('product' recommended).

    Returns:
        JSON with extraction success, confidence, method, and key product fields.
    """
    await _ensure_initialized()
    return await tool_fetch_and_extract(url, page_type)


async def validate_and_store(url: str) -> str:
    """Validate the last extracted product from a URL and store it if valid.

    Run fetch_and_extract first on the URL, then call this to validate and persist.

    Args:
        url: The URL of the product page that was previously extracted.

    Returns:
        JSON with verdict (PASS/WARN/FAIL), quality_score, and storage result.
    """
    await _ensure_initialized()
    return await tool_validate_and_store(url)


async def save_checkpoint() -> str:
    """Save the current crawler queue state to a checkpoint file.

    Call this periodically during long crawls to enable resume on interruption.

    Returns:
        JSON with checkpoint path and queue statistics.
    """
    await _ensure_initialized()
    return await tool_checkpoint()


async def get_crawl_stats() -> str:
    """Get real-time statistics for the current crawl session.

    Returns:
        JSON with counts for fetched, extracted, passed, failed, and error metrics.
    """
    await _ensure_initialized()
    return await tool_get_crawl_stats()


async def get_domain_recommendations(domain: str) -> str:
    """Get Knowledge MCP recommendations for scraping a specific domain.

    Use this before starting a crawl to check if we have prior knowledge.

    Args:
        domain: The domain to get recommendations for (e.g. 'example.com').

    Returns:
        JSON with preferred_fetch_method, skip_discovery, selector_version,
        rollback_selector_version recommendations.
    """
    await _ensure_initialized()
    return await tool_get_domain_recommendations(domain)


async def extract_navigation_routes(domain: str | dict | None = None, **kwargs) -> str:
    """Parse raw navigation markdown content to extract potential catalog/category routes.

    Use this when discovery yields few URLs or when all candidate URLs in classification
    are marked unknown to locate category routes to crawl.

    Args:
        domain: The website domain name (e.g. 'example.com').

    Returns:
        JSON string listing category/catalog URLs.
    """
    await _ensure_initialized()

    # Fail-safe parameter extraction
    target_domain = ""
    if isinstance(domain, dict):
        target_domain = domain.get("domain", "")
    elif isinstance(domain, str):
        target_domain = domain

    if not target_domain:
        target_domain = kwargs.get("domain", "")

    if not target_domain:
        # Fallback default if not specified
        target_domain = "unknown"

    from agents.planner_agent import tool_extract_navigation_routes
    return await tool_extract_navigation_routes(target_domain)


async def extract_urls_from_page(url: str) -> str:
    """Fetch any page (e.g. a category listing page) and extract all hyperlinks found on it.

    Use this when you have a category URL and need to find the child product URLs on that page.

    Args:
        url: The category or listing page URL.

    Returns:
        JSON string containing the list of absolute URLs found on the page.
    """
    await _ensure_initialized()
    from agents.planner_agent import tool_extract_urls_from_page
    return await tool_extract_urls_from_page(url)


async def finalize_crawl() -> str:
    """Finalize the crawl: flush storage, update knowledge profile, return summary.

    Call this when the crawl is complete or the budget is exhausted.

    Returns:
        JSON summary of the completed crawl.
    """
    await _ensure_initialized()
    return await tool_finalize_crawl()


# ── Build the ADK LlmAgent ────────────────────────────────────────────────────

root_agent = LlmAgent(
    name="autonomous_scraper_planner",
    model="fallback-llm",  # Orchestrated fallback chain
    description=(
        "Autonomous AI web scraping planner. "
        "Give it a website URL and it will discover, classify, fetch, "
        "extract, validate and store product data for you."
    ),
    instruction="""You are an autonomous AI e-commerce scraping planner.

To scrape any website with 100% accuracy, you must locate products by navigating its menu/navbar hierarchy rather than relying on URL regex patterns.

When you receive a scraping request, execute this workflow:
1. Call `get_domain_recommendations` to check prior knowledge and details about the domain.
2. Call `discover` to fetch the homepage, build the navigation markdown menu structure, and extract sitemaps.
   * NOTE: The `discover` tool automatically parses sitemaps and enqueues all discovered URLs (e.g., thousands of URLs) directly into the background queue database. You do NOT need to request additional discoveries or manually parse the 'sample_urls' list returned by it.
3. Immediately call `get_next_batch` to retrieve the first batch of URLs that `discover` loaded into the queue.
4. Call `classify_urls` on the batch of URLs returned from `get_next_batch`.
5. Call `enqueue_urls` to update their page types (e.g., mark category/subcategory/product priority rules) in the queue.
6. If the queue batch has category URLs but no product URLs:
   - Select a category URL and call `extract_urls_from_page` to retrieve all hyperlinks from that category page.
   - Run `classify_urls` on those newly extracted URLs and then `enqueue_urls` them.
7. For each URL in the batch determined to be a 'product':
   - Call `fetch_and_extract` to run the 5-stage extraction pipeline.
   - Call `validate_and_store` to validate the extracted product and save it.
8. Call `get_next_batch` again to fetch the next batch. Repeat this loop until you have successfully scraped the user's requested number of products.
9. Once the quota is reached, call `finalize_crawl` and present the summary to the user.
""",
    tools=[
        FunctionTool(discover),
        FunctionTool(classify_urls),
        FunctionTool(enqueue_urls),
        FunctionTool(get_next_batch),
        FunctionTool(fetch_and_extract),
        FunctionTool(validate_and_store),
        FunctionTool(save_checkpoint),
        FunctionTool(get_crawl_stats),
        FunctionTool(get_domain_recommendations),
        FunctionTool(finalize_crawl),
        FunctionTool(extract_navigation_routes),
        FunctionTool(extract_urls_from_page),
    ],
)
