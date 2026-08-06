"""shared/models/__init__.py — re-exports all shared Pydantic models."""

from shared.models.classified_url import ClassifiedURL, PageType
from shared.models.crawl_statistics import CrawlStatistics
from shared.models.crawl_task import CrawlTask, TraversalStrategy
from shared.models.extraction_result import ExtractionResult, ExtractionMethod, FieldConfidence
from shared.models.product import Product
from shared.models.product_variant import ProductVariant
from shared.models.validation_result import ValidationResult, Verdict
from shared.models.website_profile import SelectorSet, WebsiteProfile

__all__ = [
    "ClassifiedURL",
    "CrawlStatistics",
    "CrawlTask",
    "ExtractionMethod",
    "ExtractionResult",
    "FieldConfidence",
    "PageType",
    "Product",
    "ProductVariant",
    "SelectorSet",
    "TraversalStrategy",
    "ValidationResult",
    "Verdict",
    "WebsiteProfile",
]
