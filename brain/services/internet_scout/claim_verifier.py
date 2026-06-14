"""Deterministic claim-support checks for Beacon evidence snippets."""

from __future__ import annotations

import re
from dataclasses import dataclass

_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "was",
    "were",
    "with",
}


@dataclass(frozen=True)
class ClaimSupportResult:
    supported: bool
    reasons: tuple[str, ...]


def verify_claim_support(*, claim: str, citation_text: str) -> ClaimSupportResult:
    """Return whether the cited text is enough to support the stored claim."""
    normalized_claim = _normalize(claim)
    normalized_citation = _normalize(citation_text)
    if not normalized_claim:
        return ClaimSupportResult(supported=False, reasons=("empty_claim",))
    if not normalized_citation:
        return ClaimSupportResult(supported=False, reasons=("empty_citation",))

    claim_numbers = set(re.findall(r"\b\d+(?:\.\d+)?%?\b", normalized_claim))
    if claim_numbers and not claim_numbers.issubset(
        set(re.findall(r"\b\d+(?:\.\d+)?%?\b", normalized_citation))
    ):
        return ClaimSupportResult(supported=False, reasons=("number_missing",))

    if (
        normalized_claim in normalized_citation
        or normalized_citation in normalized_claim
    ):
        return ClaimSupportResult(supported=True, reasons=("text_substring_match",))

    claim_tokens = _tokens(normalized_claim)
    citation_tokens = _tokens(normalized_citation)
    if not claim_tokens or not citation_tokens:
        return ClaimSupportResult(supported=False, reasons=("no_content_tokens",))

    common = claim_tokens & citation_tokens
    required_overlap = 1 if min(len(claim_tokens), len(citation_tokens)) <= 2 else 2
    denominator = max(1, min(len(claim_tokens), len(citation_tokens)))
    overlap_ratio = len(common) / denominator
    if len(common) >= required_overlap and overlap_ratio >= 0.4:
        return ClaimSupportResult(supported=True, reasons=("token_overlap",))

    return ClaimSupportResult(supported=False, reasons=("low_token_overlap",))


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"\b[a-z0-9][a-z0-9.-]{1,}\b", value)
        if token not in _STOPWORDS
    }


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower()).strip()
