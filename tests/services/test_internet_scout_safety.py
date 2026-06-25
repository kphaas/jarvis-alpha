from __future__ import annotations

import pytest

from brain.services.internet_scout.safety import (
    ContentSafetyError,
    UrlSafetyError,
    require_safe_content_metadata,
    require_safe_url,
    validate_content_metadata,
    validate_redirect_chain,
    validate_url,
)


@pytest.mark.parametrize(
    "url",
    [
        "https://news.example.test/report",
        "http://public.example.test/a?b=c#fragment",
    ],
)
def test_public_urls_are_allowed_and_fragments_removed(url):
    result = validate_url(url)

    assert result.allowed is True
    assert result.host is not None
    assert result.normalized_url is not None
    assert "#" not in result.normalized_url


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("http://127.0.0.1:8080/admin", "blocked_non_global_ip"),
        ("http://[::1]/", "blocked_non_global_ip"),
        ("http://100.124.172.14/status", "blocked_non_global_ip"),
        ("http://jarvis-brain.tail40ed36.ts.net/health", "blocked_internal_host"),
        ("http://jarvis-gateway/health", "blocked_internal_host"),
        ("file:///tmp/page.html", "unsupported_scheme"),
        ("https://user:pass@example.test/", "url_credentials_not_allowed"),
    ],
)
def test_internal_or_unsafe_urls_are_blocked(url, reason):
    result = validate_url(url)

    assert result.allowed is False
    assert reason in result.reasons


def test_require_safe_url_raises_for_blocked_url():
    with pytest.raises(UrlSafetyError):
        require_safe_url("http://localhost:11434/api/tags")


def test_redirect_chain_blocks_internal_hop():
    with pytest.raises(UrlSafetyError, match="blocked_non_global_ip"):
        validate_redirect_chain(
            [
                "https://public.example.test/start",
                "http://169.254.169.254/latest/meta-data",
            ]
        )


def test_content_metadata_allows_text_html_with_charset():
    result = validate_content_metadata("text/html; charset=utf-8", 2048)

    assert result.allowed is True
    assert result.content_type == "text/html"


@pytest.mark.parametrize(
    "content_type",
    [
        "application/rss+xml; charset=utf-8",
        "application/atom+xml; charset=utf-8",
    ],
)
def test_content_metadata_allows_feed_xml(content_type: str) -> None:
    result = validate_content_metadata(content_type, 2048)

    assert result.allowed is True


@pytest.mark.parametrize(
    ("content_type", "content_length", "reason"),
    [
        ("image/png", 100, "unsupported_content_type"),
        ("application/octet-stream", 100, "unsupported_content_type"),
        ("text/html", 2_000_000, "content_too_large"),
    ],
)
def test_content_metadata_blocks_binary_or_oversized_content(
    content_type,
    content_length,
    reason,
):
    result = validate_content_metadata(content_type, content_length)

    assert result.allowed is False
    assert reason in result.reasons


def test_require_safe_content_metadata_raises_for_blocked_metadata():
    with pytest.raises(ContentSafetyError):
        require_safe_content_metadata("application/zip", 100)
