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
_MONTHS = {
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
    "jan",
    "feb",
    "mar",
    "apr",
    "jun",
    "jul",
    "aug",
    "sep",
    "sept",
    "oct",
    "nov",
    "dec",
}
_NEGATION_PATTERNS = (
    r"\bnot\b",
    r"\bno longer\b",
    r"\bnever\b",
    r"\bcannot\b",
    r"\bcan't\b",
    r"\bwon't\b",
    r"\bwill not\b",
    r"\bdoes not\b",
    r"\bdo not\b",
    r"\bdid not\b",
    r"\bis not\b",
    r"\bare not\b",
    r"\bwas not\b",
    r"\bwere not\b",
    r"\bunsupported\b",
    r"\bnot supported\b",
    r"\bunavailable\b",
    r"\bdeprecated\b",
)
_UNIT_PATTERN = re.compile(
    r"\b\d+(?:\.\d+)?\s*"
    r"(?:ms|milliseconds?|seconds?|minutes?|hours?|days?|weeks?|months?|years?|"
    r"kb|mb|gb|tb|tokens?|requests?|users?|seats?|dollars?|usd|%)\b"
)
_VERSION_PATTERN = re.compile(r"\bv?\d+(?:\.\d+){1,4}\b")


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

    if _has_negation(normalized_claim) != _has_negation(normalized_citation):
        return ClaimSupportResult(supported=False, reasons=("negation_mismatch",))

    claim_versions = _version_tokens(normalized_claim)
    if claim_versions and not claim_versions.issubset(
        _version_tokens(normalized_citation)
    ):
        return ClaimSupportResult(supported=False, reasons=("version_missing",))

    claim_date_markers = _date_markers(normalized_claim)
    if claim_date_markers and not claim_date_markers.issubset(
        _date_markers(normalized_citation)
    ):
        return ClaimSupportResult(supported=False, reasons=("date_marker_missing",))

    claim_units = _numeric_unit_markers(normalized_claim)
    if claim_units and not claim_units.issubset(
        _numeric_unit_markers(normalized_citation)
    ):
        return ClaimSupportResult(supported=False, reasons=("unit_marker_missing",))

    if _has_currency_marker(normalized_claim) and not _has_currency_marker(
        normalized_citation
    ):
        return ClaimSupportResult(supported=False, reasons=("currency_marker_missing",))

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


def _has_negation(value: str) -> bool:
    return any(re.search(pattern, value) for pattern in _NEGATION_PATTERNS)


def _version_tokens(value: str) -> set[str]:
    return set(_VERSION_PATTERN.findall(value))


def _date_markers(value: str) -> set[str]:
    markers = {token for token in _tokens(value) if token in _MONTHS}
    markers.update(re.findall(r"\b20\d{2}\b", value))
    markers.update(re.findall(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", value))
    markers.update(re.findall(r"\b\d{4}-\d{2}-\d{2}\b", value))
    return markers


def _numeric_unit_markers(value: str) -> set[str]:
    return {match.group(0) for match in _UNIT_PATTERN.finditer(value)}


def _has_currency_marker(value: str) -> bool:
    return "$" in value or bool(re.search(r"\b(?:usd|dollars?)\b", value))


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower()).strip()
