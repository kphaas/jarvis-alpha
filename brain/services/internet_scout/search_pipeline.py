"""Search fanout and reranking helpers for Beacon."""

from __future__ import annotations

from dataclasses import dataclass, field

from brain.services.internet_scout.models import (
    GatewaySearchResponse,
    GatewaySearchResult,
    InternetScoutRequest,
    ResearchQueryPurpose,
    SourceQualityLevel,
)
from brain.services.internet_scout.source_quality import classify_source_for_query

_QUALITY_SCORE: dict[SourceQualityLevel, int] = {
    "official": 60,
    "primary": 50,
    "trusted_secondary": 40,
    "general": 25,
    "low_confidence": 5,
    "rejected": -100,
}


@dataclass(frozen=True)
class SearchRun:
    response: GatewaySearchResponse
    purpose: ResearchQueryPurpose
    required: bool = False


@dataclass(frozen=True)
class RankedSearchResult:
    result: GatewaySearchResult
    score: int
    source_quality: SourceQualityLevel
    quality_reasons: tuple[str, ...]
    providers: tuple[str, ...]
    purposes: tuple[ResearchQueryPurpose, ...]
    required_match: bool


@dataclass
class _Candidate:
    result: GatewaySearchResult
    source_quality: SourceQualityLevel
    quality_reasons: list[str]
    providers: set[str] = field(default_factory=set)
    purposes: set[ResearchQueryPurpose] = field(default_factory=set)
    required_match: bool = False


def rank_search_results(
    *,
    request: InternetScoutRequest,
    runs: list[SearchRun],
    max_results: int,
) -> list[RankedSearchResult]:
    """Deduplicate and rank search results before extraction."""
    candidates: dict[str, _Candidate] = {}
    for run in runs:
        for result in run.response.results:
            key = _normalize_url_key(result.url)
            if not key:
                continue
            quality, reasons = classify_source_for_query(
                query=request.query,
                url=result.url,
                host=result.host,
                citation_text=result.description,
            )
            existing = candidates.get(key)
            if existing is None:
                existing = _Candidate(
                    result=result,
                    source_quality=quality,
                    quality_reasons=reasons,
                )
                candidates[key] = existing
            elif _QUALITY_SCORE[quality] > _QUALITY_SCORE[existing.source_quality]:
                existing.result = result
                existing.source_quality = quality
                existing.quality_reasons = reasons
            existing.providers.add(run.response.provider)
            existing.purposes.add(run.purpose)
            existing.required_match = existing.required_match or run.required

    ranked = [
        _ranked_candidate(candidate)
        for candidate in candidates.values()
        if candidate.source_quality != "rejected"
    ]
    return sorted(
        ranked,
        key=lambda item: (-item.score, item.result.host, item.result.url),
    )[:max_results]


def _ranked_candidate(candidate: _Candidate) -> RankedSearchResult:
    score = _QUALITY_SCORE[candidate.source_quality]
    score += min(len(candidate.providers), 3) * 8
    score += min(len(candidate.purposes), 4) * 5
    if candidate.required_match:
        score += 6
    if candidate.result.description.strip():
        score += 3
    if candidate.result.risk_markers:
        score -= 25

    providers = tuple(sorted(candidate.providers))
    purposes = tuple(sorted(candidate.purposes))
    return RankedSearchResult(
        result=candidate.result,
        score=score,
        source_quality=candidate.source_quality,
        quality_reasons=tuple(candidate.quality_reasons),
        providers=providers,
        purposes=purposes,
        required_match=candidate.required_match,
    )


def _normalize_url_key(url: str) -> str:
    return url.strip().rstrip("/").lower()
