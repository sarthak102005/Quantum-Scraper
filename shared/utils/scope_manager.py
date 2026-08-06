"""
shared/utils/scope_manager.py

Generic Crawl Scope Manager that enforces boundary constraints, handles URL
normalization, duplicate checks, and provides rich audit decisions.
"""

from __future__ import annotations

import re
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, Field

from shared.utils.logging import get_logger

logger = get_logger(__name__)


class ScopeDecision(BaseModel):
    """Rich decision response returned by the ScopeManager."""

    schema_version: str = Field(default="1.0", frozen=True)
    decision: Literal["ACCEPT", "REJECT_OUTSIDE_SCOPE", "REJECT_DUPLICATE", "DEFER"]
    reason: str
    normalized_url: str
    original_url: str
    seed_scope: str


class ScopeBoundary(BaseModel):
    """Represents the resolved boundary rules inferred from a seed URL."""

    boundary_type: Literal["ENTIRE_DOMAIN", "SUBDOMAIN", "PATH_PREFIX", "CUSTOM_PATH_PREFIX", "UNRESTRICTED"]
    allowed_host: str
    allowed_prefix: str
    is_locale_path: bool = False


class ScopeManager:
    """Infrastructure component managing URL normalization, scope validation, and auditing."""

    def __init__(self, seed_url: str, policy: str = "seed_path") -> None:
        """Initialise the ScopeManager with a seed URL and traversal policy.

        Args:
            seed_url: The starting entry point URL.
            policy: Scope configuration policy (seed_path, same_locale, same_country, entire_domain, cross_locale, cross_domain).
        """
        self.original_seed = seed_url
        self.policy = policy.lower().strip()
        self._seen_urls: set[str] = set()

        # Inferred boundary
        self.boundary = self._infer_boundary(seed_url)
        
        # Track seed URL in visited/seen set to handle duplicates
        normalized_seed = self.normalize(seed_url)
        if normalized_seed:
            self._seen_urls.add(normalized_seed)

        logger.info(
            "Crawl Scope Manager initialised",
            seed_url=seed_url,
            policy=self.policy,
            boundary_type=self.boundary.boundary_type,
            allowed_host=self.boundary.allowed_host,
            allowed_prefix=self.boundary.allowed_prefix,
            is_locale_path=self.boundary.is_locale_path,
        )

    def _infer_boundary(self, seed_url: str) -> ScopeBoundary:
        """Deduce the crawl boundary from the seed URL and policy."""
        if self.policy == "cross_domain":
            return ScopeBoundary(
                boundary_type="UNRESTRICTED",
                allowed_host="",
                allowed_prefix="/",
                is_locale_path=False,
            )

        parts = urlsplit(seed_url)
        host = parts.netloc.lower()
        path = parts.path or "/"

        # Normalize host: strip leading www. to match cleanly
        clean_host = host[4:] if host.startswith("www.") else host

        # Entire Domain policy
        if self.policy in ("entire_domain", "cross_locale"):
            return ScopeBoundary(
                boundary_type="ENTIRE_DOMAIN",
                allowed_host=clean_host,
                allowed_prefix="/",
                is_locale_path=False,
            )

        # Segment analysis
        segments = [s for s in path.split("/") if s]
        
        # Check locale first
        locale_re = re.compile(r"^[a-z]{2}([-_][a-z]{2,4})?$", re.IGNORECASE)
        if segments:
            first_segment = segments[0]
            if locale_re.match(first_segment):
                # Nested locale path check (e.g. /en/us/)
                if len(segments) > 1 and locale_re.match(segments[1]):
                    prefix = f"/{first_segment}/{segments[1]}/"
                else:
                    prefix = f"/{first_segment}/"
                
                return ScopeBoundary(
                    boundary_type="PATH_PREFIX",
                    allowed_host=clean_host,
                    allowed_prefix=prefix,
                    is_locale_path=True,
                )

        # Check subdomain second
        host_parts = clean_host.split(".")
        if len(host_parts) > 2 and host_parts[0] not in ("www", "m"):
            # e.g., us.example.com
            prefix = f"/{segments[0]}/" if segments else "/"
            return ScopeBoundary(
                boundary_type="SUBDOMAIN",
                allowed_host=clean_host,
                allowed_prefix=prefix,
                is_locale_path=False,
            )

        # Check custom path prefix third
        if segments:
            prefix = f"/{segments[0]}/"
            return ScopeBoundary(
                boundary_type="CUSTOM_PATH_PREFIX",
                allowed_host=clean_host,
                allowed_prefix=prefix,
                is_locale_path=False,
            )

        # Default to entire domain
        return ScopeBoundary(
            boundary_type="ENTIRE_DOMAIN",
            allowed_host=clean_host,
            allowed_prefix="/",
            is_locale_path=False,
        )

    def normalize(self, url: str) -> str:
        """Standarizes protocol, casing, removes fragments/trackers, and query-sorts URLs.

        Args:
            url: The absolute or relative target URL.

        Returns:
            Fully qualified normalized absolute URL string.
        """
        if not url:
            return ""

        try:
            parts = urlsplit(url)
            scheme = parts.scheme.lower() if parts.scheme else "https"
            netloc = parts.netloc.lower()

            # Trail slash normalization on path
            path = parts.path
            if path.endswith("/"):
                path = path.rstrip("/")
            if not path:
                path = "/"

            # Filter query params — strip tracking params AND common e-commerce
            # query params that select the same physical page (article=, variant=, etc.)
            query_params = parse_qsl(parts.query)
            clean_params = []
            tracking_prefixes = ("utm_", "fbclid", "gclid", "affiliate", "ref")
            # Whole-key matches for params that always resolve to the same page
            _passthrough_drop_keys = {
                "article", "variant", "color", "colour", "size",
                "sku", "selectedSku", "selectedVariant", "tab",
                "section", "anchor", "highlight",
            }
            for key, val in query_params:
                if not key.lower().startswith(tracking_prefixes) and key.lower() not in _passthrough_drop_keys:
                    clean_params.append((key, val))

            # Sort parameters to ensure unique signature
            clean_params.sort(key=lambda x: x[0])
            new_query = urlencode(clean_params) if clean_params else ""

            # Remove fragment/hash details
            return urlunsplit((scheme, netloc, path, new_query, ""))
        except Exception:
            return url.strip()

    def validate(
        self,
        url: str,
        source_page: str = "seed",
        discovery_method: str = "navigation",
    ) -> ScopeDecision:
        """Validates a target URL against host, prefix boundaries, and duplicates.

        Args:
            url: Absolute candidate URL.
            source_page: Parent URL where this candidate was discovered.
            discovery_method: Method used to extract this link (sitemap, anchor_tag, etc.)

        Returns:
            ScopeDecision tuple containing decision and reasoning.
        """
        norm_url = self.normalize(url)
        seed_scope = self.boundary.allowed_prefix

        # 1. Unrestricted policy check
        if self.boundary.boundary_type == "UNRESTRICTED":
            # Duplicate check
            if norm_url in self._seen_urls:
                dec = ScopeDecision(
                    decision="REJECT_DUPLICATE",
                    reason="URL already crawled or enqueued",
                    normalized_url=norm_url,
                    original_url=url,
                    seed_scope=seed_scope,
                )
                self._log_decision(dec, source_page, discovery_method)
                return dec
            self._seen_urls.add(norm_url)
            dec = ScopeDecision(
                decision="ACCEPT",
                reason="Unrestricted scope crawling allowed",
                normalized_url=norm_url,
                original_url=url,
                seed_scope=seed_scope,
            )
            self._log_decision(dec, source_page, discovery_method)
            return dec

        try:
            parts = urlsplit(norm_url)
            netloc = parts.netloc.lower()
            path = parts.path

            # Clean host
            clean_netloc = netloc[4:] if netloc.startswith("www.") else netloc

            # 2. Host Verification
            allowed_clean_host = self.boundary.allowed_host
            if clean_netloc != allowed_clean_host:
                decision = ScopeDecision(
                    decision="REJECT_OUTSIDE_SCOPE",
                    reason=f"Outside host boundary. Host '{clean_netloc}' does not match allowed host '{allowed_clean_host}'",
                    normalized_url=norm_url,
                    original_url=url,
                    seed_scope=seed_scope,
                )
                self._log_decision(decision, source_page, discovery_method)
                return decision

            # 3. Path Prefix Verification
            path_slashed = path if path.endswith("/") else path + "/"
            allowed_slashed = seed_scope if seed_scope.endswith("/") else seed_scope + "/"

            if not path_slashed.lower().startswith(allowed_slashed.lower()):
                decision = ScopeDecision(
                    decision="REJECT_OUTSIDE_SCOPE",
                    reason=f"Outside path boundary. Target path '{path}' does not match allowed prefix '{seed_scope}'",
                    normalized_url=norm_url,
                    original_url=url,
                    seed_scope=seed_scope,
                )
                self._log_decision(decision, source_page, discovery_method)
                return decision

            # 4. Duplicate Check
            if norm_url in self._seen_urls:
                decision = ScopeDecision(
                    decision="REJECT_DUPLICATE",
                    reason="URL already crawled or enqueued",
                    normalized_url=norm_url,
                    original_url=url,
                    seed_scope=seed_scope,
                )
                self._log_decision(decision, source_page, discovery_method)
                return decision

            # Accept link and track it as seen
            self._seen_urls.add(norm_url)
            decision = ScopeDecision(
                decision="ACCEPT",
                reason=f"Within scope host '{allowed_clean_host}' and path prefix '{seed_scope}'",
                normalized_url=norm_url,
                original_url=url,
                seed_scope=seed_scope,
            )
            self._log_decision(decision, source_page, discovery_method)
            return decision

        except Exception as e:
            decision = ScopeDecision(
                decision="REJECT_OUTSIDE_SCOPE",
                reason=f"Failed to parse or validate URL: {str(e)}",
                normalized_url=norm_url,
                original_url=url,
                seed_scope=seed_scope,
            )
            self._log_decision(decision, source_page, discovery_method)
            return decision

    def _log_decision(self, decision: ScopeDecision, source: str, method: str) -> None:
        """Outputs the structured audit trail log message for both accept and reject events."""
        from datetime import datetime
        accepted = (decision.decision == "ACCEPT")
        status = "accepted" if accepted else "rejected"
        
        logger.info(
            f"Discovery URL {status}",
            url=decision.original_url,
            normalized_url=decision.normalized_url,
            source_page=source,
            discovery_method=method,
            scope_decision=decision.decision,
            accepted=accepted,
            reason=decision.reason if not accepted else "Outside crawl scope",
            seed_scope=decision.seed_scope,
            timestamp=datetime.utcnow().isoformat() + "Z"
        )

    def classify_scope(self, url: str) -> Literal["DOMAIN", "SUBDOMAIN", "PATH", "CUSTOM"]:
        """Returns the classified scope boundary category matching a target URL."""
        if self.boundary.boundary_type == "ENTIRE_DOMAIN":
            return "DOMAIN"
        if self.boundary.boundary_type == "SUBDOMAIN":
            return "SUBDOMAIN"
        if self.boundary.boundary_type == "PATH_PREFIX" and self.boundary.is_locale_path:
            return "PATH"
        return "CUSTOM"

    def explain(self, url: str) -> str:
        """Human-readable explanation of why a URL is within or outside of scope."""
        decision = self.validate(url)
        return f"Decision: {decision.decision} (Reason: {decision.reason})"
