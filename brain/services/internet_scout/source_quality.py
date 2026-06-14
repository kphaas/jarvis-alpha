"""Citation quality policy for Beacon evidence."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import re
from urllib.parse import urlparse

from brain.services.internet_scout.claim_verifier import verify_claim_support
from brain.services.internet_scout.models import (
    EvidenceClaim,
    InternetEvidencePacket,
    InternetScoutCitationQualitySummary,
    InternetScoutLocalLLMCitation,
    SourceQualityLevel,
    SourceQualityStatus,
)
from brain.services.internet_scout.sanitizer import sanitize_untrusted_text

_OFFICIAL_QUERY_MARKERS = (
    "official",
    "api reference",
    "api docs",
    "documentation",
    "docs",
    "sdk",
    "release notes",
    "changelog",
    "status page",
    "terms of service",
    "privacy policy",
)
_OFFICIAL_HOSTS_BY_TERM: dict[str, tuple[str, ...]] = {
    "openai": ("openai.com", "platform.openai.com", "docs.openai.com"),
    "github": ("github.com", "docs.github.com"),
    "stripe": ("stripe.com", "docs.stripe.com"),
    "anthropic": ("anthropic.com", "docs.anthropic.com"),
    "google": ("google.com", "developers.google.com", "cloud.google.com"),
    "microsoft": ("microsoft.com", "learn.microsoft.com"),
    "apple": ("apple.com", "developer.apple.com"),
    "aws": ("aws.amazon.com", "docs.aws.amazon.com"),
    "amazon": ("amazon.com", "aws.amazon.com", "docs.aws.amazon.com"),
    "cloudflare": ("cloudflare.com", "developers.cloudflare.com"),
}
_LOW_CONFIDENCE_HOSTS = (
    "community.openai.com",
    "community.anthropic.com",
    "stackoverflow.com",
    "youtube.com",
    "youtu.be",
    "tiktok.com",
    "reddit.com",
    "x.com",
    "twitter.com",
    "facebook.com",
    "instagram.com",
    "pinterest.com",
    "quora.com",
)
_PRIMARY_PATH_MARKERS = (
    "/docs",
    "/documentation",
    "/api",
    "/reference",
    "/developer",
    "/developers",
    "/learn",
    "/support",
    "/help",
)
_TRUSTED_SUFFIXES = (".gov", ".edu")
_QUALITY_RANK: dict[SourceQualityLevel, int] = {
    "official": 5,
    "primary": 4,
    "trusted_secondary": 3,
    "general": 2,
    "low_confidence": 1,
    "rejected": 0,
}


@dataclass(frozen=True)
class EvaluatedCitation:
    citation: InternetScoutLocalLLMCitation
    accepted: bool
    prompt_injection_rejected: bool = False
    unsupported_claim: bool = False


@dataclass(frozen=True)
class CitationQualityEvaluation:
    citations: list[InternetScoutLocalLLMCitation]
    summary: InternetScoutCitationQualitySummary


@dataclass(frozen=True)
class _Policy:
    official_source_required: bool
    required_source_hosts: tuple[str, ...]


def evaluate_citation_quality(
    packet: InternetEvidencePacket,
    *,
    max_citations: int = 25,
) -> CitationQualityEvaluation:
    """Rank and filter citations before they enter a local model prompt."""
    policy = _policy_for_query(packet.request.query)
    source_by_url = {source.url: source for source in packet.sources}
    evaluated: list[EvaluatedCitation] = []

    for claim in packet.claims[:max_citations]:
        source = source_by_url.get(claim.source_url)
        if source is None:
            continue
        citation = _citation_for_claim(
            claim=claim,
            host=source.host,
            content_hash=source.content_hash,
            policy=policy,
        )
        claim_support = verify_claim_support(
            claim=claim.claim,
            citation_text=citation.citation_text,
        )
        if not claim_support.supported:
            citation.quality_reasons.extend(
                f"claim_support:{reason}" for reason in claim_support.reasons
            )
        is_accepted_citation, injection_rejected = _is_accepted(
            citation,
            policy,
            claim_supported=claim_support.supported,
        )
        evaluated.append(
            EvaluatedCitation(
                citation=citation,
                accepted=is_accepted_citation,
                prompt_injection_rejected=injection_rejected,
                unsupported_claim=not claim_support.supported,
            )
        )

    accepted_citations = sorted(
        (item.citation for item in evaluated if item.accepted),
        key=lambda item: (-_QUALITY_RANK[item.source_quality], item.source_url),
    )
    summary = _summary(
        policy=policy,
        evaluated=evaluated,
        accepted_count=len(accepted_citations),
    )
    return CitationQualityEvaluation(citations=accepted_citations, summary=summary)


def classify_source_for_query(
    *,
    query: str | None,
    url: str,
    host: str,
    citation_text: str,
) -> tuple[SourceQualityLevel, list[str]]:
    """Classify a candidate source with the same policy used for citations."""
    return _classify_source(
        url=url,
        host=host,
        citation_text=citation_text,
        policy=_policy_for_query(query),
    )


def _citation_for_claim(
    *,
    claim: EvidenceClaim,
    host: str,
    content_hash: str,
    policy: _Policy,
) -> InternetScoutLocalLLMCitation:
    quality, reasons = _classify_source(
        url=claim.source_url,
        host=host,
        citation_text=claim.citation_text,
        policy=policy,
    )
    sanitized = sanitize_untrusted_text(claim.citation_text)
    if sanitized.risk_markers:
        quality = "rejected"
        reasons = [
            *reasons,
            *[f"prompt_injection:{marker}" for marker in sanitized.risk_markers],
        ]
    return InternetScoutLocalLLMCitation(
        claim=claim.claim,
        source_url=claim.source_url,
        host=host,
        content_hash=content_hash,
        citation_text=sanitized.text,
        confidence=claim.confidence,
        source_quality=quality,
        quality_reasons=reasons[:10],
    )


def _policy_for_query(query: str | None) -> _Policy:
    normalized = _normalize(query or "")
    official_source_required = any(
        marker in normalized for marker in _OFFICIAL_QUERY_MARKERS
    )
    hosts: list[str] = []
    for term, official_hosts in _OFFICIAL_HOSTS_BY_TERM.items():
        if term in normalized:
            hosts.extend(official_hosts)
    hosts.extend(_domain_tokens(normalized))
    return _Policy(
        official_source_required=official_source_required,
        required_source_hosts=tuple(dict.fromkeys(hosts)),
    )


def _classify_source(
    *,
    url: str,
    host: str,
    citation_text: str,
    policy: _Policy,
) -> tuple[SourceQualityLevel, list[str]]:
    reasons: list[str] = []
    parsed = urlparse(url)
    path = parsed.path.lower()
    normalized_host = host.lower().strip(".")

    if _host_matches_official(normalized_host, policy.required_source_hosts):
        return "official", ["matches_required_official_host"]

    if _is_low_confidence_host(normalized_host):
        reasons.append("low_confidence_host")
        return "low_confidence", reasons

    if normalized_host.endswith(_TRUSTED_SUFFIXES):
        reasons.append("trusted_public_suffix")
        return "trusted_secondary", reasons

    if any(marker in path for marker in _PRIMARY_PATH_MARKERS):
        reasons.append("primary_source_path")
        return "primary", reasons

    if policy.official_source_required:
        reasons.append("official_source_required")
        if policy.required_source_hosts:
            reasons.append("host_not_official_for_query")
        return "general", reasons

    if citation_text.strip():
        return "general", ["cited_search_result"]
    return "low_confidence", ["empty_citation_text"]


def _is_accepted(
    citation: InternetScoutLocalLLMCitation,
    policy: _Policy,
    *,
    claim_supported: bool,
) -> tuple[bool, bool]:
    injection_rejected = any(
        reason.startswith("prompt_injection:") for reason in citation.quality_reasons
    )
    if injection_rejected:
        return False, True
    if not claim_supported:
        return False, False
    if (
        policy.official_source_required
        and policy.required_source_hosts
        and citation.source_quality != "official"
    ):
        return False, False
    if citation.source_quality in {"rejected", "low_confidence"}:
        return False, False
    return True, False


def _summary(
    *,
    policy: _Policy,
    evaluated: list[EvaluatedCitation],
    accepted_count: int,
) -> InternetScoutCitationQualitySummary:
    quality_counts = Counter(item.citation.source_quality for item in evaluated)
    rejected_count = len(evaluated) - accepted_count
    injection_rejected = sum(1 for item in evaluated if item.prompt_injection_rejected)
    unsupported_count = sum(1 for item in evaluated if item.unsupported_claim)
    warnings: list[str] = []

    if (
        policy.official_source_required
        and policy.required_source_hosts
        and quality_counts["official"] == 0
    ):
        warnings.append("No official source matched the source policy for this query.")
    elif policy.official_source_required and not policy.required_source_hosts:
        warnings.append("No official source host could be inferred for this query.")
    if rejected_count:
        warnings.append(
            f"{rejected_count} citation(s) were excluded by source quality."
        )
    if injection_rejected:
        warnings.append(
            f"{injection_rejected} citation(s) contained prompt-injection markers."
        )
    if unsupported_count:
        warnings.append(
            f"{unsupported_count} citation(s) were excluded because the claim was not "
            "supported by the citation text."
        )

    status: SourceQualityStatus = "supported"
    if accepted_count == 0:
        status = "insufficient"
        warnings.append("No acceptable citations are available for a sourced answer.")
    elif accepted_count == 1 and not (
        policy.official_source_required and quality_counts["official"] >= 1
    ):
        status = "weak"
        warnings.append("Only one acceptable citation is available.")

    return InternetScoutCitationQualitySummary(
        status=status,
        accepted_citation_count=accepted_count,
        rejected_citation_count=rejected_count,
        official_source_count=quality_counts["official"],
        verified_claim_count=accepted_count,
        unsupported_claim_count=unsupported_count,
        prompt_injection_rejection_count=injection_rejected,
        official_source_required=policy.official_source_required,
        required_source_hosts=list(policy.required_source_hosts),
        warnings=warnings[:20],
    )


def _host_matches_official(host: str, required_hosts: tuple[str, ...]) -> bool:
    for required in required_hosts:
        if host == required:
            return True
        # Bare company domains should not let arbitrary community/forum subdomains
        # satisfy official-source requirements.
        if required.count(".") == 1 and host == f"www.{required}":
            return True
        if required.count(".") > 1 and host.endswith(f".{required}"):
            return True
    return False


def _is_low_confidence_host(host: str) -> bool:
    return any(
        host == low_host or host.endswith(f".{low_host}")
        for low_host in _LOW_CONFIDENCE_HOSTS
    )


def _domain_tokens(query: str) -> list[str]:
    tokens = re.findall(r"\b[a-z0-9.-]+\.[a-z]{2,}\b", query)
    return [token.strip(".") for token in tokens]


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower()).strip()
