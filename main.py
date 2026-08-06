"""
main.py

CLI entry point for the Autonomous AI Web Scraping Framework.
Loads settings, parses instructions, builds the ADK agent, and starts the task.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from agents.planner_agent import run_scraping_task, set_crawler_mcp
from shared.models.crawl_task import CrawlTask, TraversalStrategy
from shared.utils.config import get_config
from shared.utils.logging import get_logger, setup_logging

logger = get_logger(__name__)


def parse_args() -> argparse.Namespace:
    """Parses command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Autonomous AI Web Scraping Framework CLI Runner"
    )
    parser.add_argument(
        "prompt",
        type=str,
        help="Natural language instruction for the scraping agent (e.g. 'Scrape 10 product pages from example.com')",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Custom path to config.yaml file",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Override crawl budget page count",
    )
    return parser.parse_args()


async def async_main() -> int:
    """Async wrapper initialization."""
    args = parse_args()

    # Load Config singleton
    try:
        config = get_config()
    except Exception as e:
        print(f"Error loading configuration: {str(e)}")
        return 1

    # Setup Logging configuration
    setup_logging(
        level=config.logging.level,
        log_file=config.logging.output,
    )

    logger.info("Initializing Autonomous AI Web Scraper Framework")

    # Handle argument overrides
    if args.max_pages:
        config.concurrency.global_max_requests = args.max_pages

    # Extract target domain from user prompt string if possible
    # We create a dummy CrawlTask to populate the CrawlerMCP before the planner runs
    import re
    from urllib.parse import urlsplit
    
    # Simple regex search for URLs in user prompt
    urls = re.findall(r"https?://[^\s/$.?#].[^\s]*", args.prompt)
    if urls:
        seed_url = urls[0].rstrip("/.,;:")
        domain = urlsplit(seed_url).netloc
    else:
        # Fallback if URL is missing
        seed_url = "https://example.com"
        domain = "example.com"

    # Instantiate task models
    task = CrawlTask(
        seed_url=seed_url,
        domain=domain,
        max_pages=args.max_pages or 50,
        traversal_strategy=TraversalStrategy.BFS,
    )

    # Register task-bound MCP components into agent singletons
    set_crawler_mcp(task, config)

    logger.info("Starting ADK Agent orchestrator execution loop")
    try:
        summary_response = await run_scraping_task(args.prompt, config)
        print("\n=== Agent Scraping Summary ===")
        print(summary_response)
        print("==============================\n")
        return 0
    except Exception as e:
        logger.exception("An unhandled exception crashed the runner execution")
        print(f"\nScraping runner error: {str(e)}\n")
        return 1


def main() -> None:
    """Command-line entry point."""
    sys.exit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
