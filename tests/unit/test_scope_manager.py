"""
tests/unit/test_scope_manager.py

Unit tests verifying ScopeManager normalization, boundary detection,
decision routing, and auditing logic.
"""

from __future__ import annotations

import pytest

from shared.utils.scope_manager import ScopeBoundary, ScopeManager


def test_normalization() -> None:
    manager = ScopeManager("https://example.com/us/")

    # Tracking parameters removal
    assert manager.normalize("https://example.com/us/p/123?utm_source=google&utm_medium=cpc") == "https://example.com/us/p/123"
    assert manager.normalize("https://example.com/us/p/123?affiliate=test&ref=12") == "https://example.com/us/p/123"

    # Fragments removal
    assert manager.normalize("https://example.com/us/p/123#reviews-section") == "https://example.com/us/p/123"

    # Sorting query keys
    assert manager.normalize("https://example.com/us/p/123?z=1&a=2") == "https://example.com/us/p/123?a=2&z=1"

    # Trailing slash
    assert manager.normalize("https://example.com/us/") == "https://example.com/us"


def test_root_domain_boundary() -> None:
    # Root domain seed
    manager = ScopeManager("https://example.com/")
    assert manager.boundary.boundary_type == "ENTIRE_DOMAIN"
    assert manager.boundary.allowed_prefix == "/"

    # Allows everything on same domain
    assert manager.validate("https://example.com/en-us/p1").decision == "ACCEPT"
    assert manager.validate("https://example.com/fr-fr/p1").decision == "ACCEPT"
    assert manager.validate("https://www.example.com/p1").decision == "ACCEPT"

    # Rejects different domains
    assert manager.validate("https://another.com/p1").decision == "REJECT_OUTSIDE_SCOPE"


def test_subdomain_boundary() -> None:
    # Subdomain seed
    manager = ScopeManager("https://us.example.com/")
    assert manager.boundary.boundary_type == "SUBDOMAIN"
    assert manager.boundary.allowed_host == "us.example.com"

    # Allows same subdomain
    assert manager.validate("https://us.example.com/products").decision == "ACCEPT"
    
    # Rejects parent and other subdomains
    assert manager.validate("https://example.com/products").decision == "REJECT_OUTSIDE_SCOPE"
    assert manager.validate("https://fr.example.com/products").decision == "REJECT_OUTSIDE_SCOPE"


def test_locale_prefixed_boundary() -> None:
    # Locale prefixed path seed
    manager = ScopeManager("https://example.com/en-us/")
    assert manager.boundary.boundary_type == "PATH_PREFIX"
    assert manager.boundary.allowed_prefix == "/en-us/"
    assert manager.boundary.is_locale_path is True

    # Allows within locale path prefix
    assert manager.validate("https://example.com/en-us/products/excavator").decision == "ACCEPT"
    
    # Rejects outside locale path prefix (cross-locale links)
    assert manager.validate("https://example.com/en-gb/products/excavator").decision == "REJECT_OUTSIDE_SCOPE"
    assert manager.validate("https://example.com/fr-fr/products/excavator").decision == "REJECT_OUTSIDE_SCOPE"


def test_custom_prefixed_boundary() -> None:
    # Custom prefixed path seed
    manager = ScopeManager("https://example.com/products/")
    assert manager.boundary.boundary_type == "CUSTOM_PATH_PREFIX"
    assert manager.boundary.allowed_prefix == "/products/"

    # Allows within prefix
    assert manager.validate("https://example.com/products/excavator").decision == "ACCEPT"
    
    # Rejects outside prefix
    assert manager.validate("https://example.com/accessories/spools").decision == "REJECT_OUTSIDE_SCOPE"


def test_hreflang_and_country_switchers() -> None:
    # E.g. seed is US locale
    manager = ScopeManager("https://www.jcb.com/en-us/")

    # Alternative hreflang links (outside US scope)
    assert manager.validate("https://www.jcb.com/en-gb/products").decision == "REJECT_OUTSIDE_SCOPE"
    assert manager.validate("https://www.jcb.com/fr-fr/products").decision == "REJECT_OUTSIDE_SCOPE"

    # Footer country switcher links (outside US scope)
    assert manager.validate("https://www.jcb.com/en-za/").decision == "REJECT_OUTSIDE_SCOPE"


def test_duplicate_rejection() -> None:
    manager = ScopeManager("https://example.com/en-us/")

    # Enqueue a URL once
    assert manager.validate("https://example.com/en-us/p1").decision == "ACCEPT"
    
    # Enqueue same URL again -> rejects as duplicate
    assert manager.validate("https://example.com/en-us/p1").decision == "REJECT_DUPLICATE"


def test_case_insensitive_path_verification() -> None:
    manager = ScopeManager("https://example.com/en-US/")
    
    # Lowercase path should be accepted
    assert manager.validate("https://example.com/en-us/products/excavator").decision == "ACCEPT"
    
    # Uppercase path should be accepted
    assert manager.validate("https://example.com/en-US/products/loader").decision == "ACCEPT"
    
    # Different locale should still be rejected
    assert manager.validate("https://example.com/en-gb/products/excavator").decision == "REJECT_OUTSIDE_SCOPE"
