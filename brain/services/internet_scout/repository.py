"""Persistence helpers for Beacon evidence packets."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import cast
from uuid import UUID

from brain.services.internet_scout.models import (
    EvidenceClaim,
    InternetEvidencePacket,
    InternetScoutRequest,
    PolicyDecision,
    Sensitivity,
    SourceReference,
)

JsonObject = dict[str, object]


class InternetScoutRepository:
    def __init__(self, conn) -> None:
        self.conn = conn

    async def create_request(
        self,
        *,
        user_id: str,
        request: InternetScoutRequest,
        decision: PolicyDecision,
    ) -> UUID:
        row = await self.conn.fetchrow(
            """
            INSERT INTO public.alpha_internet_requests (
                user_id, requester, selected_tool, sensitivity, policy_tier,
                status, request_payload_hash, request_shape, policy_reason,
                blocked_reasons
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9, $10::jsonb)
            RETURNING id
            """,
            user_id,
            request.requester,
            decision.tool.value,
            request.sensitivity,
            decision.tier,
            "running" if decision.allowed else "blocked",
            _request_hash(request),
            json.dumps(_request_shape(request)),
            decision.reason,
            json.dumps(decision.blocked_reasons),
        )
        if not row:
            raise RuntimeError("Beacon request insert returned no row")
        return row["id"]

    async def store_packet(
        self,
        *,
        request_id: UUID,
        packet: InternetEvidencePacket,
    ) -> None:
        source_ids: dict[str, UUID] = {}
        for source in packet.sources:
            source_ids[source.url] = await self._insert_source(request_id, source)

        for claim in packet.claims:
            source_id = source_ids.get(claim.source_url)
            if source_id is None:
                continue
            await self._insert_evidence(request_id, source_id, claim)

    async def record_tool_event(
        self,
        *,
        request_id: UUID,
        tool: str,
        event_type: str,
        status: str,
        metadata: JsonObject | None = None,
        payload_hash: str | None = None,
        error_text: str | None = None,
    ) -> None:
        await self.conn.execute(
            """
            INSERT INTO public.alpha_internet_tool_events (
                request_id, tool, event_type, status, payload_hash,
                error_digest, metadata
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
            """,
            request_id,
            tool,
            event_type,
            status,
            payload_hash,
            _digest(error_text) if error_text else None,
            json.dumps(metadata or {}),
        )

    async def mark_request_succeeded(self, request_id: UUID) -> None:
        await self.conn.execute(
            """
            UPDATE public.alpha_internet_requests
            SET status = 'succeeded', error_digest = NULL
            WHERE id = $1
            """,
            request_id,
        )

    async def mark_request_failed(self, request_id: UUID, error_text: str) -> None:
        await self.conn.execute(
            """
            UPDATE public.alpha_internet_requests
            SET status = 'failed', error_digest = $2
            WHERE id = $1
            """,
            request_id,
            _digest(error_text),
        )

    async def load_packet(self, request_id: UUID) -> InternetEvidencePacket | None:
        request_row = await self.conn.fetchrow(
            """
            SELECT requester, request_shape
            FROM public.alpha_internet_requests
            WHERE id = $1
            """,
            request_id,
        )
        if not request_row:
            return None

        source_rows = await self.conn.fetch(
            """
            SELECT id, url, host, title, content_hash, fetched_at
            FROM public.alpha_internet_sources
            WHERE request_id = $1
            ORDER BY created_at ASC
            """,
            request_id,
        )
        claim_rows = await self.conn.fetch(
            """
            SELECT source.url AS source_url, evidence.claim,
                   evidence.citation_text, evidence.confidence
            FROM public.alpha_internet_evidence AS evidence
            JOIN public.alpha_internet_sources AS source
              ON source.id = evidence.source_id
            WHERE evidence.request_id = $1
            ORDER BY evidence.created_at ASC
            """,
            request_id,
        )
        shape = _jsonb(request_row["request_shape"])
        request = InternetScoutRequest(
            query=None,
            urls=[],
            max_pages=_int_json(shape.get("max_pages"), default=1),
            max_depth=_int_json(shape.get("max_depth"), default=0),
            needs_interaction=bool(shape.get("needs_interaction", False)),
            sensitivity=_sensitivity_json(shape.get("sensitivity")),
            requester=str(request_row["requester"]),
        )
        sources = [
            SourceReference(
                url=row["url"],
                host=row["host"],
                title=row["title"],
                content_hash=row["content_hash"],
                fetched_at=row["fetched_at"],
            )
            for row in source_rows
        ]
        claims = [
            EvidenceClaim(
                claim=row["claim"],
                source_url=row["source_url"],
                citation_text=row["citation_text"],
                confidence=row["confidence"],
            )
            for row in claim_rows
        ]
        return InternetEvidencePacket(request=request, sources=sources, claims=claims)

    async def _insert_source(
        self,
        request_id: UUID,
        source: SourceReference,
    ) -> UUID:
        row = await self.conn.fetchrow(
            """
            INSERT INTO public.alpha_internet_sources (
                request_id, url, host, title, content_hash, fetched_at
            )
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
            """,
            request_id,
            source.url,
            source.host,
            source.title,
            source.content_hash,
            source.fetched_at,
        )
        if not row:
            raise RuntimeError("Beacon source insert returned no row")
        return row["id"]

    async def _insert_evidence(
        self,
        request_id: UUID,
        source_id: UUID,
        claim: EvidenceClaim,
    ) -> None:
        await self.conn.execute(
            """
            INSERT INTO public.alpha_internet_evidence (
                request_id, source_id, claim, citation_text, confidence
            )
            VALUES ($1, $2, $3, $4, $5)
            """,
            request_id,
            source_id,
            claim.claim,
            claim.citation_text,
            claim.confidence,
        )


def _request_hash(request: InternetScoutRequest) -> str:
    payload = request.model_dump(mode="json")
    return _digest(json.dumps(payload, sort_keys=True))


def _request_shape(request: InternetScoutRequest) -> JsonObject:
    return {
        "has_query": bool(request.query),
        "url_count": len(request.urls),
        "tool_hint": request.tool_hint.value if request.tool_hint else None,
        "max_pages": request.max_pages,
        "max_depth": request.max_depth,
        "needs_interaction": request.needs_interaction,
        "sensitivity": request.sensitivity,
    }


def _digest(value: str) -> str:
    return "sha256:" + sha256(value.encode("utf-8")).hexdigest()


def _jsonb(value: object) -> JsonObject:
    if value is None:
        return {}
    if isinstance(value, str):
        return json.loads(value)
    if isinstance(value, dict):
        return value
    raise TypeError(f"Expected JSON object, got {type(value).__name__}")


def _int_json(value: object, *, default: int) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int | float | str | bytes | bytearray):
        return int(value)
    return default


def _sensitivity_json(value: object) -> Sensitivity:
    if value in {"normal", "privacy", "legal", "financial", "minor"}:
        return cast(Sensitivity, value)
    return "normal"
