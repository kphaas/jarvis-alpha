"""Persistence helpers for Beacon evidence packets."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Any, cast
from uuid import UUID

from brain.services.internet_scout.models import (
    EvidenceClaim,
    InternetEvidencePacket,
    InternetScoutMemoryPromotion,
    InternetScoutMemoryPromotionCandidate,
    InternetScoutRequest,
    PolicyDecision,
    Sensitivity,
    SourceReference,
)
from brain.services.internet_scout.memory_promotions import (
    validate_memory_promotion_candidate,
)
from brain.services.internet_scout.sanitizer import sanitize_untrusted_text

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
        status_override: str | None = None,
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
            status_override or ("running" if decision.allowed else "blocked"),
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

    async def count_recent_browser_runs(self, user_id: str) -> int:
        value = await self.conn.fetchval(
            """
            SELECT COUNT(*)
            FROM public.alpha_internet_tool_events AS event
            JOIN public.alpha_internet_requests AS request
              ON request.id = event.request_id
            WHERE request.user_id = $1
              AND event.tool = 'browser_use'
              AND event.event_type = 'browser_run'
              AND event.status = 'succeeded'
              AND event.created_at >= NOW() - INTERVAL '1 hour'
            """,
            user_id,
        )
        return int(value or 0)

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

    async def create_memory_promotions(
        self,
        *,
        request_id: UUID,
        packet: InternetEvidencePacket,
        target_user_id: UUID,
        requested_by: str,
        candidates: list[InternetScoutMemoryPromotionCandidate],
    ) -> list[InternetScoutMemoryPromotion]:
        promotions: list[InternetScoutMemoryPromotion] = []
        for candidate in candidates:
            claim, source = validate_memory_promotion_candidate(
                packet=packet,
                candidate=candidate,
            )
            row = await self.conn.fetchrow(
                """
                INSERT INTO public.alpha_internet_memory_promotions (
                    request_id, target_user_id, requested_by, source_url,
                    source_host, source_content_hash, citation_text,
                    proposed_fact, category, reviewer_note
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                RETURNING *
                """,
                request_id,
                target_user_id,
                requested_by,
                source.url,
                source.host,
                source.content_hash,
                claim.citation_text,
                candidate.proposed_fact.strip(),
                candidate.category,
                candidate.reviewer_note,
            )
            if not row:
                raise RuntimeError("Beacon memory promotion insert returned no row")
            promotions.append(_promotion_from_row(row))
        return promotions

    async def review_memory_promotion(
        self,
        *,
        promotion_id: UUID,
        decision: str,
        reviewer: str,
        reviewer_note: str | None = None,
    ) -> InternetScoutMemoryPromotion | None:
        row = await self.conn.fetchrow(
            """
            SELECT *
            FROM public.alpha_internet_memory_promotions
            WHERE id = $1
              AND status = 'pending_review'
            """,
            promotion_id,
        )
        if row is None:
            return None

        if decision == "reject":
            updated = await self.conn.fetchrow(
                """
                UPDATE public.alpha_internet_memory_promotions
                SET status = 'rejected',
                    reviewed_by = $2,
                    reviewed_at = NOW(),
                    reviewer_note = COALESCE($3, reviewer_note)
                WHERE id = $1
                RETURNING *
                """,
                promotion_id,
                reviewer,
                reviewer_note,
            )
            return _promotion_from_row(updated)

        proposed_fact = str(row["proposed_fact"])
        sanitized_fact = sanitize_untrusted_text(proposed_fact, max_chars=500)
        if sanitized_fact.risk_markers or sanitized_fact.text != proposed_fact.strip():
            updated = await self.conn.fetchrow(
                """
                UPDATE public.alpha_internet_memory_promotions
                SET status = 'failed',
                    reviewed_by = $2,
                    reviewed_at = NOW(),
                    semantic_result = $3::jsonb,
                    reviewer_note = COALESCE($4, reviewer_note)
                WHERE id = $1
                RETURNING *
                """,
                promotion_id,
                reviewer,
                json.dumps(
                    {
                        "saved": False,
                        "reason": "promoted_fact_failed_review_validation",
                    }
                ),
                reviewer_note,
            )
            return _promotion_from_row(updated)

        semantic_result = await self.conn.fetchval(
            """
            SELECT public.save_beacon_semantic_memory($1::uuid, $2, $3, $4, $5)
            """,
            row["target_user_id"],
            row["proposed_fact"],
            row["category"],
            row["source_url"],
            row["source_content_hash"],
        )
        semantic_payload = _jsonb(semantic_result)
        status = "promoted" if semantic_payload.get("saved") is True else "skipped"
        updated = await self.conn.fetchrow(
            """
            UPDATE public.alpha_internet_memory_promotions
            SET status = $2,
                reviewed_by = $3,
                reviewed_at = NOW(),
                semantic_saved_at = CASE WHEN $2 = 'promoted' THEN NOW() ELSE NULL END,
                semantic_result = $4::jsonb,
                reviewer_note = COALESCE($5, reviewer_note)
            WHERE id = $1
            RETURNING *
            """,
            promotion_id,
            status,
            reviewer,
            json.dumps(semantic_payload),
            reviewer_note,
        )
        return _promotion_from_row(updated)

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


def _promotion_from_row(row: Any) -> InternetScoutMemoryPromotion:
    if row is None:
        raise RuntimeError("Beacon memory promotion row is missing")
    return InternetScoutMemoryPromotion(
        id=row["id"],
        request_id=row["request_id"],
        target_user_id=row["target_user_id"],
        requested_by=row["requested_by"],
        source_url=row["source_url"],
        source_host=row["source_host"],
        source_content_hash=row["source_content_hash"],
        citation_text=row["citation_text"],
        proposed_fact=row["proposed_fact"],
        category=row["category"],
        status=row["status"],
        semantic_result=_jsonb(row["semantic_result"]),
        reviewer_note=row["reviewer_note"],
        created_at=row["created_at"],
        reviewed_at=row["reviewed_at"],
    )
