"""
tests/integration/test_crawl_pipeline.py

Integration test validating the full scrape pipeline:
Discovery -> Classification -> Crawler enqueuing -> Execution -> Extraction -> Validation -> Storage.
"""

from __future__ import annotations

from pathlib import Path
import pytest
from aioresponses import aioresponses

from mcps.classification.classification_mcp import ClassificationMCP
from mcps.crawler.crawler_mcp import CrawlerMCP
from mcps.discovery.discovery_mcp import DiscoveryMCP
from mcps.execution.execution_mcp import ExecutionMCP
from mcps.extraction.extraction_mcp import ExtractionMCP
from mcps.storage.storage_mcp import StorageMCP
from mcps.validation.validation_mcp import ValidationMCP
from shared.models import CrawlTask
from shared.utils.config import get_config


@pytest.mark.asyncio
async def test_full_pipeline_flow(tmp_path: Path) -> None:
    config = get_config()
    orig_dir = config.output.directory
    config.output.directory = str(tmp_path)

    # Load fixtures
    with open("tests/fixtures/sample_robots.txt", "r", encoding="utf-8") as f:
        robots_txt = f.read()
    with open("tests/fixtures/sample_sitemap.xml", "r", encoding="utf-8") as f:
        sitemap_xml = f.read()
    with open("tests/fixtures/sample_product.html", "r", encoding="utf-8") as f:
        product_html = f.read()

    try:
        task = CrawlTask(
            seed_url="https://example-shop.com",
            domain="example-shop.com",
            max_pages=5
        )

        # Init MCPs
        discovery = DiscoveryMCP(config)
        classification = ClassificationMCP()
        crawler = CrawlerMCP(task, config)
        execution = ExecutionMCP(config)
        extraction = ExtractionMCP(config)
        validation = ValidationMCP()
        storage = StorageMCP(config)

        with aioresponses() as m:
            # Mock Discovery URLs fetch
            m.get("https://example-shop.com/robots.txt", status=200, body=robots_txt)
            m.get("https://example-shop.com/sitemap.xml", status=200, body=sitemap_xml)
            m.get("https://example-shop.com/sitemap_products.xml", status=404)

            # Mock Page smart_fetch URL
            product_url = "https://example-shop.com/product/wireless-headphones-pro"
            m.get(product_url, status=200, body=product_html)

            # Step 1: Discovery
            disc_res = await discovery.discover(task)
            assert len(disc_res.urls) > 0

            # Step 2: Classification
            classified = await classification.classify(disc_res.urls, disc_res.profile)
            
            # Step 3: Crawler enqueueing
            await crawler.enqueue(classified)
            
            # Step 4: Next batch
            batch = await crawler.next_batch(1)
            assert len(batch) == 1
            target_url = batch[0].url

            # Step 5: Execution Smart Fetch
            fetch_res = await execution.smart_fetch(target_url, disc_res.profile)
            assert fetch_res.success is True
            assert fetch_res.html is not None

            # Step 6: Extraction
            extract_res = await extraction.extract(fetch_res.html, disc_res.profile)
            assert extract_res.success is True

            # Step 7: Validation
            val_res = await validation.validate(extract_res)
            assert val_res.verdict == "PASS"

            # Step 8: Storage write
            store_res = await storage.write(extract_res.product, val_res)
            assert store_res.success is True

        # Shutdown
        await execution.close()
        await storage.close()

        # Assert outputs created
        csv_file = tmp_path / "products.csv"
        assert csv_file.exists()

    finally:
        config.output.directory = orig_dir
