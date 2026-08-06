"""
mcps/extraction/semantic_extractor.py

Semantic Extractor — leverages generic DOM structure, tags, classes, labels,
and regular expression patterns to extract product features without LLMs.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from shared.models.extraction_result import ExtractionResult, FieldConfidence
from shared.models.product import Product
from shared.utils.logging import get_logger

logger = get_logger(__name__)


async def extract(html: str, source_url: str) -> ExtractionResult:
    """Infer product data using semantic layout guidelines.

    Args:
        html: HTML source.
        source_url: Target URL.

    Returns:
        ExtractionResult containing inferred attributes.
    """
    logger.info("Running Semantic Extraction Stage", url=source_url)
    soup = BeautifulSoup(html, "html.parser")

    title = None
    price = None
    currency = None
    brand = None
    sku = None
    availability = None
    specifications: dict[str, str] = {}

    # Generic blocklist for layout/navigation headers
    generic_titles = {
        "shop", "cart", "checkout", "search", "menu", "navigation", "home", "account",
        "accessories", "apparel", "parts", "log in", "sign up", "shop all", "vehicle accessories",
        "accessory packages", "essentials", "collections", "digital catalogs", "limited-time collaborations",
        "featured", "new arrivals", "sale", "licensed products", "racing", "experience", "owner center",
        "kawasaki", "husqvarna", "bobcat", "jcb", "jlg", "all", "online", "store", "official", "site",
        "portal", "catalog", "motors", "corp", "usa", "u.s.a", "corporation", "brand", "brands"
    }

    def is_generic(val: str | None) -> bool:
        if not val:
            return True
        val_clean = val.lower().strip()
        if val_clean in generic_titles:
            return True
        # Split into alphanumeric words and check if all of them are generic
        words = [re.sub(r"\W+", "", w) for w in val_clean.split()]
        words = [w for w in words if w]
        if not words:
            return True
        return all(w in generic_titles for w in words)

    # 1. Infer Title — Derive from URL slug first as it is the most reliable, generic identifier
    if source_url:
        try:
            parsed_url = urlsplit(source_url)
            path_segments = [s for s in parsed_url.path.strip("/").split("/") if s]
            if path_segments:
                last_segment = path_segments[-1]
                # Ensure it contains at least one letter and isn't just a short hash/ID or generic
                if any(c.isalpha() for c in last_segment) and len(last_segment) > 2:
                    derived = last_segment.replace("-", " ").replace("_", " ").title()
                    if not is_generic(derived):
                        title = derived
        except Exception:
            pass

    if not title:
        title_el = soup.find(class_=re.compile(
            r"trimName|product[-_]?title|model[-_]?name|vehicle[-_]?name|"
            r"headTwo|pdp[-_]title|product__title|item[-_]?name|prod[-_]?name|"
            r"product[-_]?name|product[-_]?heading",
            re.I,
        ))
        if title_el:
            title = title_el.get_text().strip()
            if is_generic(title):
                title = None
    if not title:
        h1_candidates = []
        for h1 in soup.find_all("h1"):
            text = h1.get_text().strip()
            if not text or is_generic(text) or len(text) < 3:
                continue
            # Score candidate: longer specific text is better
            score = len(text)
            # Penalize generic-looking titles (single-word headers are usually categories)
            if len(text.split()) < 2:
                score -= 30
            # Boost mixed-case or uppercase specific headers
            if any(w.isupper() for w in text.split() if len(w) > 2):
                score += 20
            h1_candidates.append((score, text))

        if h1_candidates:
            h1_candidates.sort(key=lambda x: x[0], reverse=True)
            title = h1_candidates[0][1]
        # H1 was all generic (e.g. "SHOP KAWASAKI") — fall through to h2/h3
    if not title or is_generic(title):
        h2_candidates = []
        for heading in soup.find_all(["h2", "h3"]):
            text = heading.get_text().strip()
            if not text or is_generic(text) or len(text) < 5:
                continue
            # Prefer headings inside <main>, <article>, or product-like containers
            in_main = bool(heading.find_parent(["main", "article"]) or
                           heading.find_parent(class_=re.compile(r"product|pdp|detail|item", re.I)))
            score = len(text) + (30 if in_main else 0)
            if len(text.split()) < 2:
                score -= 20
            h2_candidates.append((score, text))

        if h2_candidates:
            h2_candidates.sort(key=lambda x: x[0], reverse=True)
            title = h2_candidates[0][1]

    # Fallback to page <title> if still empty or generic
    if not title or is_generic(title):
        page_title_el = soup.find("title")
        if page_title_el:
            raw_page_title = page_title_el.get_text().strip()
            # Remove brand suffixes (e.g. "| Kawasaki Motors Corp., U.S.A.", "- Husqvarna", etc.)
            for sep in ("|", "-", "::"):
                if sep in raw_page_title:
                    parts = raw_page_title.split(sep)
                    candidate = parts[0].strip()
                    if candidate and not is_generic(candidate):
                        title = candidate
                        break
            else:
                if not is_generic(raw_page_title):
                    title = raw_page_title

    # 2. Infer Price and Currency symbols
    # Look for common symbols near number formats inside elements containing price or pricing classes
    price_pattern = re.compile(r"([\$\€\£\¥\u20b9])\s*([\d,]+\.?\d*)")
    
    # Try finding elements with price-related class names
    price_elements = soup.find_all(class_=re.compile(r"price|pricing|amount|cost", re.I))
    for el in price_elements:
        text = el.get_text().strip()
        match = price_pattern.search(text)
        if match:
            currency_symbol = match.group(1)
            # Map symbol to standard currency codes
            symbol_map = {"$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY", "₹": "INR"}
            currency = symbol_map.get(currency_symbol, "USD")
            
            try:
                price = float(match.group(2).replace(",", ""))
                break
            except ValueError:
                continue

    # Fallback price regex search across entire HTML if class checks missed
    if price is None:
        match = price_pattern.search(soup.get_text())
        if match:
            symbol_map = {"$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY", "₹": "INR"}
            currency = symbol_map.get(match.group(1), "USD")
            try:
                price = float(match.group(2).replace(",", ""))
            except ValueError:
                pass

    # 3. Infer brand from elements with brand classes or attributes
    brand_el = soup.find(class_=re.compile(r"brand|manufacturer|vendor", re.I))
    if brand_el:
        brand = brand_el.get_text().strip()
    else:
        # Check standard properties
        itemprop_brand = soup.find(itemprop="brand")
        if itemprop_brand:
            brand = itemprop_brand.get_text().strip()

    # Domain-based brand fallback for manufacturer sites
    if not brand and source_url:
        domain = urlsplit(source_url).netloc.lower()
        if "kawasaki" in domain:
            brand = "Kawasaki"
        elif "husqvarna" in domain:
            brand = "Husqvarna"
        elif "jcb" in domain:
            brand = "JCB"
        elif "jlg" in domain:
            brand = "JLG"
        else:
            parts = domain.replace("www.", "").split(".")
            if parts:
                brand = parts[0].capitalize()

    # 4. Infer SKU
    sku_el = soup.find(class_=re.compile(r"sku|mpn|model-number|model_num", re.I))
    if sku_el:
        sku = sku_el.get_text().replace("SKU:", "").replace("Model:", "").strip()

    # 5. Infer Availability
    text_content = soup.get_text().lower()
    if any(term in text_content for term in ("in stock", "in_stock", "available", "add to cart")):
        availability = "in_stock"
    elif any(term in text_content for term in ("out of stock", "out_of_stock", "sold out")):
        availability = "out_of_stock"

    # 6. Parse description (paragraphs of text near the title/H1)
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
    description = " ".join(desc_parts) if desc_parts else None

    # 7. Parse specification tables (<table> or <dl> tags)
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

    # 8. Parse specifications from list items or divs under spec headings
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

    # Fallback: scan any list item or div with class containing spec/attribute containing colons
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

    # Determine confidence levels
    if not title:
        return ExtractionResult(success=False, confidence=0.0, method="semantic", source_url=source_url)

    product = Product(
        source_url=source_url,
        domain=urlsplit(source_url).netloc,
        title=title,
        price=price,
        currency=currency,
        brand=brand,
        sku=sku,
        availability=availability or "in_stock",
        description=description,
        specifications=specifications,
        extraction_method="semantic",
    )

    has_price_currency = price is not None and currency is not None
    has_desc_specs = bool(description) or len(specifications) > 0

    base_score = 0.50
    if has_price_currency:
        base_score += 0.10
    if has_desc_specs:
        base_score += 0.10

    confidence = min(base_score, 0.70)

    field_confs = [
        FieldConfidence(field_name="title", score=0.70 if title else 0.0, method="semantic"),
        FieldConfidence(field_name="brand", score=0.70 if brand else 0.0, method="semantic"),
        FieldConfidence(field_name="price", score=0.70 if price else 0.0, method="semantic"),
        FieldConfidence(field_name="currency", score=0.70 if currency else 0.0, method="semantic"),
        FieldConfidence(field_name="description", score=0.70 if description else 0.0, method="semantic"),
    ]

    return ExtractionResult(
        success=True,
        product=product,
        confidence=confidence,
        method="semantic",
        field_confidences=field_confs,
        source_url=source_url,
    )
