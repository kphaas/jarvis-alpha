"""Deterministic public-internet safety checks for Beacon."""

from __future__ import annotations

import ipaddress
from urllib.parse import ParseResult, urlparse, urlunparse

from brain.services.internet_scout.models import ContentSafetyResult, UrlSafetyResult

BLOCKED_HOST_EXACT = {
    "0.0.0.0",
    "localhost",
    "metadata.google.internal",
}
BLOCKED_HOST_PREFIXES = ("jarvis-",)
BLOCKED_HOST_SUFFIXES = (
    ".internal",
    ".lan",
    ".local",
    ".localhost",
    ".tail40ed36.ts.net",
)
ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_CONTENT_TYPES = {
    "application/json",
    "application/xhtml+xml",
    "application/xml",
    "text/html",
    "text/markdown",
    "text/plain",
    "text/xml",
}
DEFAULT_MAX_CONTENT_BYTES = 1_000_000


class UrlSafetyError(ValueError):
    """Raised when a URL or redirect chain is not public-internet safe."""


class ContentSafetyError(ValueError):
    """Raised when response metadata is not safe for extraction."""


def validate_url(url: str) -> UrlSafetyResult:
    """Return a policy result for a URL without making any network request."""
    parsed = _parse_url(url)
    if parsed is None:
        return UrlSafetyResult(
            original_url=url,
            allowed=False,
            reasons=["invalid_url"],
        )

    reasons: list[str] = []
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        reasons.append("unsupported_scheme")
    if parsed.username or parsed.password:
        reasons.append("url_credentials_not_allowed")

    host = _normalized_host(parsed)
    if not host:
        reasons.append("missing_host")
    else:
        reasons.extend(_host_block_reasons(host))

    normalized_url = _normalized_url(parsed, host) if host else None
    return UrlSafetyResult(
        original_url=url,
        normalized_url=normalized_url,
        host=host,
        allowed=not reasons,
        reasons=reasons,
    )


def require_safe_url(url: str) -> UrlSafetyResult:
    result = validate_url(url)
    if not result.allowed:
        raise UrlSafetyError(", ".join(result.reasons))
    return result


def validate_redirect_chain(urls: list[str]) -> list[UrlSafetyResult]:
    """Validate every hop; any redirect to an internal host blocks the fetch."""
    if not urls:
        raise UrlSafetyError("redirect_chain_empty")
    results = [validate_url(url) for url in urls]
    blocked = [result for result in results if not result.allowed]
    if blocked:
        reasons = sorted({reason for result in blocked for reason in result.reasons})
        raise UrlSafetyError(", ".join(reasons))
    return results


def validate_content_metadata(
    content_type: str | None,
    content_length: int | None,
    *,
    max_bytes: int = DEFAULT_MAX_CONTENT_BYTES,
) -> ContentSafetyResult:
    reasons: list[str] = []
    normalized_type = _normalized_content_type(content_type)

    if content_length is not None and content_length < 0:
        reasons.append("negative_content_length")
    if content_length is not None and content_length > max_bytes:
        reasons.append("content_too_large")
    if normalized_type is not None and normalized_type not in ALLOWED_CONTENT_TYPES:
        reasons.append("unsupported_content_type")

    return ContentSafetyResult(
        allowed=not reasons,
        content_type=normalized_type,
        content_length=content_length,
        reasons=reasons,
    )


def require_safe_content_metadata(
    content_type: str | None,
    content_length: int | None,
    *,
    max_bytes: int = DEFAULT_MAX_CONTENT_BYTES,
) -> ContentSafetyResult:
    result = validate_content_metadata(
        content_type,
        content_length,
        max_bytes=max_bytes,
    )
    if not result.allowed:
        raise ContentSafetyError(", ".join(result.reasons))
    return result


def _parse_url(url: str) -> ParseResult | None:
    try:
        parsed = urlparse(url.strip())
        _ = parsed.port
    except ValueError:
        return None
    return parsed


def _normalized_host(parsed: ParseResult) -> str | None:
    host = parsed.hostname
    if not host:
        return None
    host = host.strip().rstrip(".").lower()
    try:
        return host.encode("idna").decode("ascii")
    except UnicodeError:
        return None


def _normalized_url(parsed: ParseResult, host: str) -> str:
    netloc = f"[{host}]" if ":" in host and not host.startswith("[") else host
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"
    path = parsed.path or "/"
    return urlunparse(
        (
            parsed.scheme.lower(),
            netloc,
            path,
            parsed.params,
            parsed.query,
            "",
        )
    )


def _host_block_reasons(host: str) -> list[str]:
    reasons: list[str] = []
    if host in BLOCKED_HOST_EXACT:
        reasons.append("blocked_internal_host")
    if host.startswith(BLOCKED_HOST_PREFIXES):
        reasons.append("blocked_internal_host")
    if host.endswith(BLOCKED_HOST_SUFFIXES):
        reasons.append("blocked_internal_host")

    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return reasons

    if not address.is_global:
        reasons.append("blocked_non_global_ip")
    return reasons


def _normalized_content_type(content_type: str | None) -> str | None:
    if content_type is None:
        return None
    value = content_type.split(";", 1)[0].strip().lower()
    return value or None
