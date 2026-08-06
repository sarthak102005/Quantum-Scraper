"""
mcps/classification/heuristics.py

Precision Page Type Evidence Collector and Multi-Class Intent Classifier.
Standardizes page checks across e-commerce, manufacturer, B2B, and B2C websites
with strict exclusions and custom NAVIGATION_HUB intent classification.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from shared.models.classified_url import PageType
from shared.models.website_profile import WebsiteProfile
from shared.utils.config import get_config

DEFAULT_WEIGHTS: dict[str, dict[str, float]] = {
    "PRODUCT": {
        "jsonld_product": 60.0,
        "add_to_cart": 40.0,
        "buy_now": 40.0,
        "request_quote": 30.0,
        "sku_present": 30.0,
        "variants_present": 25.0,
        "specs_present": 25.0,
        "availability_present": 20.0,
        "reviews_present": 20.0,
        "gallery_present": 20.0,
        "product_url_keyword": 40.0,
        "digits_in_last_segment": 25.0,
        "deep_segments": 20.0,
        "deep_catalog_leaf": 25.0,
        # Negative signals
        "non_catalog_exclusion": -100.0,
        "catalog_category_listing": -35.0,
        "category_grid": -50.0,
        "pagination_controls": -50.0,
        "filters_sorting": -40.0,
        "service_keywords": -30.0,
        "blog_metadata": -50.0,
        "plural_suffix": -25.0,
        "hub_url_keyword": -35.0,
        "hub_path_contains": -35.0,
        "hub_keywords": -35.0,
        "product_query_param": 40.0,
        "compare_products": -40.0,
    },
    "CATEGORY": {
        "category_url_keyword": 45.0,
        "category_grid": 40.0,
        "filters_sorting": 40.0,
        "pagination_controls": 35.0,
        "plural_suffix": 20.0,
        "series_range_suffix": 20.0,
        "add_to_cart": 10.0,
        "compare_products": 20.0,
        "catalog_category_listing": 35.0,
        # Negative signals
        "non_catalog_exclusion": -100.0,
        "digits_in_last_segment": -20.0,
        "product_url_keyword": -30.0,
        "deep_catalog_leaf": -20.0,
        "hub_url_keyword": -25.0,
    },
    "PRODUCT_FAMILY": {
        "series_range_suffix": 35.0,
        "plural_suffix": 20.0,
        "category_grid": 40.0,
        "compare_products": 30.0,
        "filters_sorting": 20.0,
        "product_url_keyword": 20.0,
        "add_to_cart": 15.0,
        "request_quote": 15.0,
        "specs_present": 10.0,
        "catalog_category_listing": 20.0,
        "deep_catalog_leaf": 15.0,
        # Negative signals
        "non_catalog_exclusion": -100.0,
        "digits_in_last_segment": -10.0,
        "hub_url_keyword": -20.0,
        "category_url_keyword": -45.0,
    },
    "NAVIGATION_HUB": {
        "hub_url_keyword": 35.0,
        "hub_path_contains": 40.0,
        "hub_keywords": 30.0,
        "hub_heading_density": 35.0,
        "hub_card_layout": 35.0,
        "category_grid": 20.0,
        # Negative signals
        "non_catalog_exclusion": -100.0,
        "digits_in_last_segment": -20.0,
        "product_url_keyword": -35.0,
        "add_to_cart": -30.0,
        "sku_present": -30.0,
        "jsonld_product": -40.0,
        "product_query_param": -40.0,
    },
    "SERVICE": {
        "service_url_keyword": 55.0,
        "service_keywords": 45.0,
    },
    "SUPPORT": {
        "support_url_keyword": 40.0,
        "support_keywords": 30.0,
        "pdf_download": 20.0,
    },
    "DOCUMENTATION": {
        "support_url_keyword": 30.0,
        "pdf_download": 35.0,
    },
    "BLOG": {
        "blog_url_keyword": 60.0,
        "blog_metadata": 50.0,
    },
    "NEWS": {
        "blog_url_keyword": 60.0,
        "blog_metadata": 45.0,
    },
    "LANDING_PAGE": {
        "home_path": 60.0,
    },
    "DEALER": {
        "dealer_url_keyword": 60.0,
        "dealer_locator": 50.0,
    },
    "SEARCH_RESULTS": {
        "search_url_keyword": 65.0,
        "pagination_controls": 30.0,
    },
    "ACCOUNT": {
        "account_url_keyword": 65.0,
    },
}


def collect_evidence(
    url: str,
    html_snippet: str | None = None,
    profile: WebsiteProfile | None = None,
) -> dict[str, bool]:
    """Inspects structural and semantic markers to gather evidence signals."""
    path = urlsplit(url).path.lower()
    query = urlsplit(url).query.lower()
    
    signals: dict[str, bool] = {}

    # Strict non-catalog exclusion check (events, blogs, corporate, about, careers, store locators, guides/academy articles)
    exclusions = [
        "/explore/", "/engage/", "/events/", "/blog/", "/article/", "/news/", "/press/", 
        "/careers/", "/about/", "/corporate/", "/contact/", "/history/", "/anniversary/", 
        "/locations/", "/store-locator/", "/find-a-dealer/", "/find-dealer/",
        "/discover/", "/academy/", "/learn/", "/how-to/", "/guides/", "/insights/"
    ]
    signals["non_catalog_exclusion"] = any(x in path for x in exclusions)

    # 1. URL Path Keywords
    signals["product_url_keyword"] = any(x in path for x in ["/product/", "/p/", "/item/", "/dp/", "/pd/", "/product-page/"])
    if profile and profile.product_url_patterns:
        if any(p.replace(".*", "") in path for p in profile.product_url_patterns):
            signals["product_url_keyword"] = True

    signals["category_url_keyword"] = any(x in path for x in [
        "/c/", "/category/", "/categories/", "/collections/", "/dept/", "/browse/",
        "/product-range/", "/guide/", "/guides/", "/collection/", "/gift-guides/", "/holiday-gift-guides/"
    ])
    if profile and profile.category_url_patterns:
        if any(p.replace(".*", "") in path for p in profile.category_url_patterns):
            signals["category_url_keyword"] = True

    signals["blog_url_keyword"] = any(x in path for x in ["/blog/", "/article/", "/news/", "/post/"])
    signals["search_url_keyword"] = any(x in query or x in path for x in ["/search", "q=", "s=", "search="])
    signals["account_url_keyword"] = any(x in path for x in ["/account", "/cart", "/checkout", "/login", "/register", "/admin"])
    signals["dealer_url_keyword"] = any(x in path for x in ["/dealer", "/find-dealer", "/distributor", "/dealer-locator", "/locations", "/store-locator", "/find-a-dealer"])
    signals["support_url_keyword"] = any(x in path for x in ["/support", "/manuals", "/downloads", "/datasheets", "/brochures", "/repair", "/parts"])
    signals["service_url_keyword"] = any(x in path for x in ["/financing", "/leasing", "/warranty", "/rental", "/consulting"])
    
    # Home check
    signals["home_path"] = path == "" or path == "/" or path == "/index" or path == "/index.html"

    # 2. Path Segment Depth & Suffix Check
    segments = [
        s for s in path.strip("/").split("/") 
        if s and len(s) > 2 and not re.match(r"^[a-z]{2}-[a-z]{2}$", s)
    ]
    signals["deep_segments"] = len(segments) >= 3

    last_seg = segments[-1] if segments else ""
    signals["plural_suffix"] = last_seg.endswith("s") and not any(
        last_seg.endswith(w) for w in ["press", "glass", "status", "focus", "class", "basis", "axis", "gas", "-us", "news"]
    )
    signals["series_range_suffix"] = any(x in last_seg for x in ["-series", "-range", "-category", "-catalog", "-class", "-type", "-family"])
    
    _has_digits = bool(re.search(r"\d+", last_seg))
    # Exclude common pricing/filter numbers in list URLs (e.g. under-100, gifts-under-25, price-100-200)
    if _has_digits and any(x in last_seg.lower() for x in ["under-", "over-", "price-", "gifts-"]):
        _has_digits = False
    signals["digits_in_last_segment"] = _has_digits

    # NAVIGATION_HUB path check
    hub_keywords_list = [
        "industry", "industries", "application", "applications", "market", "markets",
        "solution", "solutions", "equipment", "machines", "attachments", "implements",
        "product-lines", "product-groups", "product-range", "series", "collections",
        "brands", "business-units", "use-cases", "sectors", "segments", "verticals",
        "fleet", "operational"
    ]
    last_seg_lower = last_seg.lower()
    signals["hub_url_keyword"] = last_seg_lower in hub_keywords_list
    signals["hub_path_contains"] = any(f"/{kw}/" in path or path.endswith(f"/{kw}") for kw in hub_keywords_list)
    signals["product_query_param"] = any(x in query for x in ["variant=", "sku=", "model=", "id=", "product=", "item=", "options="])

    # 2b. Catalog Depth Segment Check
    catalog_root_patterns = ["/products/", "/machines/", "/equipment/", "/categories/", "/collections/", "/shop/"]
    latest_pat = None
    latest_idx = -1
    for root_pat in catalog_root_patterns:
        idx = path.rfind(root_pat)
        if idx > latest_idx:
            latest_idx = idx
            latest_pat = root_pat

    signals["deep_catalog_leaf"] = False
    signals["catalog_category_listing"] = False

    if latest_pat:
        after_root = path[latest_idx + len(latest_pat):]
        depth_segments = [s for s in after_root.split("/") if s]
        if len(depth_segments) >= 2:
            signals["deep_catalog_leaf"] = True
        elif len(depth_segments) == 1:
            signals["catalog_category_listing"] = True

    if signals.get("deep_catalog_leaf"):
        signals["hub_path_contains"] = False
        signals["hub_url_keyword"] = False

    # 3. HTML Snippet Extraction (if available)
    if html_snippet:
        snippet_lower = html_snippet.lower()

        # Product-specific elements
        signals["jsonld_product"] = "schema.org/product" in snippet_lower or re.search(r'"@type"\s*:\s*"product"', snippet_lower) or 'itemtype="http://schema.org/product"' in snippet_lower
        signals["add_to_cart"] = any(term in snippet_lower for term in ["add-to-cart", "addtocart", "add to cart", "add to basket", "add-to-basket", "addtobasket"])
        signals["buy_now"] = any(term in snippet_lower for term in ["buy-now", "buynow", "buy now", "buy_now"])
        signals["request_quote"] = any(term in snippet_lower for term in ["request a quote", "request quote", "requestquote", "get a quote", "quote-request", "request-a-quote"])
        signals["sku_present"] = any(term in snippet_lower for term in ["sku", "model number", "model no", "part number", "part no", "mpn", "model-number"])
        signals["variants_present"] = any(term in snippet_lower for term in ["select size", "select color", "variants", "product-option", "choose size", "choose color"])
        signals["specs_present"] = any(term in snippet_lower for term in ["specifications", "specs table", "tech specs", "specification", "key specifications"])
        signals["availability_present"] = any(term in snippet_lower for term in ["in stock", "out of stock", "instock", "availability", "in_stock", "out_of_stock"])
        signals["reviews_present"] = any(term in snippet_lower for term in ["review", "rating", "star-rating", "customer review", "ratingvalue"])
        signals["gallery_present"] = any(term in snippet_lower for term in ["gallery", "thumbnails", "alt-images", "product-gallery", "image-gallery"])

        # Category-specific elements
        signals["compare_products"] = any(term in snippet_lower for term in ["compare", "compare products", "product comparison", "add to compare"])
        signals["category_grid"] = any(term in snippet_lower for term in [
            "product-list", "category-products", "subcategories", "filter-results", "grid-view", "list-view",
            "product-grid", "productrepeat", "product-card", "product-tile", "product-item", "grid-item",
            "list-container", "listcontainer"
        ])
        signals["pagination_controls"] = 'rel="next"' in snippet_lower or 'class="pagination"' in snippet_lower or 'class="pager"' in snippet_lower
        signals["filters_sorting"] = any(term in snippet_lower for term in ["filter-sidebar", "facets", "filter-by", "shop-filters", "refine-results", "sort-by", "sortby", "orderby"])
        
        # Navigation Hub intent signals
        signals["hub_keywords"] = any(term in snippet_lower for term in ["industries", "solutions", "applications", "markets", "segments", "brands", "business units", "use cases"])
        signals["hub_heading_density"] = any(term in snippet_lower for term in ["<h2>industries", "<h3>industries", "<h2>solutions", "<h3>solutions", "<h2>applications", "<h3>applications", "<h2>markets", "<h3>markets"])
        signals["hub_card_layout"] = any(term in snippet_lower for term in ["card", "tile", "grid", "panel-grid", "hub-grid", "landing-grid"])

        # Other types elements
        signals["service_keywords"] = any(term in snippet_lower for term in ["financing", "financing available", "apply for financing", "leasing options", "warranty options", "construction equipment financing"])
        signals["pdf_download"] = ".pdf" in snippet_lower or "download manual" in snippet_lower or "download datasheet" in snippet_lower
        signals["dealer_locator"] = any(term in snippet_lower for term in ["locate a dealer", "find dealer", "distributor locator", "dealer locator"])
        signals["blog_metadata"] = "<article" in snippet_lower or "blog-post" in snippet_lower or "post-meta" in snippet_lower or "published on" in snippet_lower

    else:
        # Default all HTML signals to False if snippet is missing
        html_signals = [
            "jsonld_product", "add_to_cart", "buy_now", "request_quote", "sku_present",
            "variants_present", "specs_present", "availability_present", "reviews_present",
            "gallery_present", "compare_products", "category_grid", "pagination_controls",
            "filters_sorting", "service_keywords", "pdf_download", "dealer_locator", "blog_metadata",
            "hub_keywords", "hub_heading_density", "hub_card_layout"
        ]
        for sig in html_signals:
            signals[sig] = False

    return signals


def classify_url(
    url: str,
    html_snippet: str | None = None,
    profile: WebsiteProfile | None = None,
) -> tuple[PageType, float, list[str]]:
    """Evaluates collected evidence against multi-class weights to determine page type.

    Args:
        url: Absolute target URL.
        html_snippet: Optional string snippet of fetched HTML.
        profile: Optional WebsiteProfile carrying site-specific patterns.

    Returns:
        tuple containing (PageType, confidence_score, list_of_fired_signals).
    """
    signals = collect_evidence(url, html_snippet=html_snippet, profile=profile)
    config = get_config()
    
    # Allow weight overrides from config if defined
    weights = getattr(config.classification, "weights", DEFAULT_WEIGHTS)
    if not isinstance(weights, dict):
        weights = DEFAULT_WEIGHTS

    scores: dict[PageType, float] = {
        ptype: 0.0 for ptype in DEFAULT_WEIGHTS.keys()
    }
    # Precision threshold: Base score for UNKNOWN is set high to prevent low-evidence classifications
    scores["UNKNOWN"] = 35.0

    # Store explanation signal strings
    signals_fired: list[str] = []

    for ptype, ptype_weights in weights.items():
        for sig_name, sig_weight in ptype_weights.items():
            if signals.get(sig_name, False):
                scores[ptype] = scores.get(ptype, 0.0) + sig_weight
                weight_sign = "+" if sig_weight >= 0 else ""
                signals_fired.append(f"{sig_name} for {ptype} ({weight_sign}{sig_weight})")

    # Pick the winning page type
    best_ptype: PageType = "UNKNOWN"
    best_score = -9999.0
    for ptype, score in scores.items():
        if score > best_score:
            best_score = score
            best_ptype = ptype

    # Normalize score as a confidence rating between 0.0 and 1.0
    confidence = min(max(best_score / 100.0, 0.0), 1.0)

    # Filter out duplicate signals to keep logs readable
    unique_signals = list(set(signals_fired))

    return best_ptype, confidence, unique_signals
