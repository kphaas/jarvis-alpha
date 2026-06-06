"""Evidence packet helpers for Beacon."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256

from brain.services.internet_scout.models import (
    EvidenceClaim,
    InternetEvidencePacket,
    InternetScoutRequest,
    SourceReference,
)
from brain.services.internet_scout.safety import require_safe_url


def content_hash(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def build_source_reference(
    *,
    url: str,
    content: str,
    title: str | None = None,
    fetched_at: datetime | None = None,
) -> SourceReference:
    safe_url = require_safe_url(url)
    if safe_url.normalized_url is None or safe_url.host is None:
        raise ValueError("safe URL result is incomplete")
    return SourceReference(
        url=safe_url.normalized_url,
        host=safe_url.host,
        content_hash=content_hash(content),
        fetched_at=fetched_at or datetime.now(UTC),
        title=title,
    )


def build_evidence_packet(
    *,
    request: InternetScoutRequest,
    sources: list[SourceReference],
    claims: list[EvidenceClaim] | None = None,
) -> InternetEvidencePacket:
    return InternetEvidencePacket(
        request=request,
        sources=sources,
        claims=claims or [],
    )
