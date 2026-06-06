"""Reviewed Beacon evidence promotion helpers."""

from __future__ import annotations

from brain.services.internet_scout.models import (
    EvidenceClaim,
    InternetEvidencePacket,
    InternetScoutMemoryPromotionCandidate,
    SourceReference,
)
from brain.services.internet_scout.sanitizer import sanitize_untrusted_text


class MemoryPromotionPolicyError(ValueError):
    """Raised when evidence cannot be safely promoted into memory."""


def validate_memory_promotion_candidate(
    *,
    packet: InternetEvidencePacket,
    candidate: InternetScoutMemoryPromotionCandidate,
) -> tuple[EvidenceClaim, SourceReference]:
    """Return the citable claim/source pair after anti-poisoning checks."""

    if candidate.claim_index >= len(packet.claims):
        raise MemoryPromotionPolicyError("claim_index_out_of_range")
    sanitized_fact = sanitize_untrusted_text(candidate.proposed_fact, max_chars=500)
    if sanitized_fact.risk_markers:
        raise MemoryPromotionPolicyError("proposed_fact_contains_untrusted_directive")
    if sanitized_fact.text != candidate.proposed_fact.strip():
        raise MemoryPromotionPolicyError("proposed_fact_must_be_clean_text")

    claim = packet.claims[candidate.claim_index]
    source = next(
        (item for item in packet.sources if item.url == claim.source_url),
        None,
    )
    if source is None:
        raise MemoryPromotionPolicyError("claim_source_not_found")
    if source.content_hash.strip() == "":
        raise MemoryPromotionPolicyError("source_hash_required")
    return claim, source
