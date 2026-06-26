"""Durable Beacon web-cache indexing and reranking helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from uuid import UUID

from brain.services.internet_scout.models import (
    SourceQualityLevel,
)
from brain.services.internet_scout.safety import require_safe_url
from brain.services.internet_scout.source_quality import classify_source_for_query

DEFAULT_WEB_CACHE_TTL_HOURS = 168
MAX_CACHE_EXCERPT_CHARS = 1000
MAX_CACHE_TERMS = 80
MAX_CACHE_LOOKUP_CANDIDATES = 50

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9-]{2,}")
_STOP_WORDS = {
    "about",
    "after",
    "also",
    "and",
    "are",
    "can",
    "com",
    "for",
    "from",
    "has",
    "how",
    "into",
    "latest",
    "more",
    "news",
    "not",
    "official",
    "org",
    "the",
    "this",
    "with",
    "www",
}
_QUALITY_SCORE: dict[SourceQualityLevel, int] = {
    "official": 60,
    "primary": 50,
    "trusted_secondary": 40,
    "general": 25,
    "low_confidence": 5,
    "rejected": -100,
}


@dataclass(frozen=True)
class WebCacheEntry:
    """One persisted public-web evidence cache row."""

    id: UUID
    url: str
    host: str
    title: str | None
    content_hash: str
    excerpt: str
    search_terms: tuple[str, ...]
    fetched_at: datetime
    expires_at: datetime
    access_count: int = 0


@dataclass(frozen=True)
class RankedWebCacheEntry:
    """Cache row with deterministic local rerank metadata."""

    entry: WebCacheEntry
    score: int
    source_quality: SourceQualityLevel
    quality_reasons: tuple[str, ...]
    matched_terms: tuple[str, ...]


def cache_url_key(url: str) -> str:
    safe_url = require_safe_url(url)
    if safe_url.normalized_url is None:
        raise ValueError("cache URL is not normalizable")
    return safe_url.normalized_url.strip().rstrip("/").lower()


def cache_search_terms(*parts: object) -> tuple[str, ...]:
    seen: set[str] = set()
    terms: list[str] = []
    for part in parts:
        if not isinstance(part, str):
            continue
        for token in _TOKEN_RE.findall(part.lower()):
            if token in _STOP_WORDS or token in seen:
                continue
            seen.add(token)
            terms.append(token)
            if len(terms) >= MAX_CACHE_TERMS:
                return tuple(terms)
    return tuple(terms)


def cache_excerpt(value: str) -> str:
    return " ".join(value.strip().split())[:MAX_CACHE_EXCERPT_CHARS]


def rank_web_cache_entries(
    *,
    query: str | None,
    entries: list[WebCacheEntry],
    max_results: int,
) -> list[RankedWebCacheEntry]:
    query_terms = set(cache_search_terms(query or ""))
    ranked: list[RankedWebCacheEntry] = []
    for entry in entries:
        quality, reasons = classify_source_for_query(
            query=query,
            url=entry.url,
            host=entry.host,
            citation_text=entry.excerpt,
        )
        if quality == "rejected":
            continue
        haystack_terms = set(entry.search_terms)
        matched_terms = tuple(sorted(query_terms & haystack_terms))
        title_terms = set(cache_search_terms(entry.title or ""))
        score = _QUALITY_SCORE[quality]
        score += min(len(matched_terms), 10) * 8
        score += min(len(query_terms & title_terms), 5) * 5
        score += min(entry.access_count, 10)
        if entry.excerpt:
            score += 3
        ranked.append(
            RankedWebCacheEntry(
                entry=entry,
                score=score,
                source_quality=quality,
                quality_reasons=tuple(reasons),
                matched_terms=matched_terms,
            )
        )
    return sorted(
        ranked,
        key=lambda item: (-item.score, item.entry.host, item.entry.url),
    )[: max(max_results, 0)]
