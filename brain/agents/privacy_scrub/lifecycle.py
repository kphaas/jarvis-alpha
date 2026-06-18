"""Authorization vault and local removal request lifecycle.

P5-A turns the existing P4 control-plane tables into an operator-usable ledger:
signed authorizations, request state, lifecycle events, and proof references.
It intentionally performs no broker submission, browser automation, email send,
or other outbound work.

P5-B adds a dry-run executor envelope. Brain prepares and records the reviewed
request, then calls only the Gateway dry-run contract. Gateway still performs no
public egress for dry runs, and Brain never owns broker/browser/email execution.

P5-C adds one live-preflight adapter for BeenVerified. It remains Gateway-owned,
kill-switch gated, fresh-approval-bound, and limited to a fixed target HTTP GET:
no broker form submission, browser automation, email, SMS, or PII payload submit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

import asyncpg

from brain.agents.privacy_scrub.crypto import EncryptedPayload, PrivacyCrypto
from brain.agents.privacy_scrub.state import get_subject
from brain.services.gateway_egress import GatewayEgressError, call_gateway_proxy
from jarvis_common.logging_config import get_logger

logger = get_logger("privacy_scrub.lifecycle")


class PrivacyLifecycleError(ValueError):
    """Base error for authorization and removal lifecycle operations."""


class PrivacyLifecycleNotFound(PrivacyLifecycleError):
    """The requested lifecycle resource is not visible through RLS."""


class PrivacyLifecycleAuthorizationRequired(PrivacyLifecycleError):
    """A lifecycle operation requires an active signed authorization."""


class PrivacyLifecycleTransitionError(PrivacyLifecycleError):
    """The requested lifecycle transition is invalid."""


class PrivacyLifecycleGatewayError(PrivacyLifecycleError):
    """Gateway dry-run preflight failed."""


class GatewayDryRunCaller(Protocol):
    async def __call__(
        self,
        path: str,
        payload: dict[str, object],
        *,
        timeout_s: int,
    ) -> dict[str, object]:
        """Call a Gateway egress endpoint."""


@dataclass(frozen=True, slots=True)
class StoredPrivacyAuthorization:
    id: UUID
    subject_id: UUID
    authorization_type: str
    status: str
    authorization_payload_hash: str
    payload_key_version: str
    expires_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime | None
    updated_at: datetime | None


@dataclass(frozen=True, slots=True)
class StoredRemovalRequest:
    id: UUID
    subject_id: UUID
    target_id: str
    target_name: str
    target_category: str
    authorization_id: UUID
    action_id: UUID | None
    lifecycle_status: str
    request_payload_hash: str
    payload_key_version: str
    target_opt_out_method: str
    current_evidence_count: int
    next_check_at: datetime | None
    last_event_at: datetime | None
    dry_run_payload_hash: str | None
    dry_run_payload_key_version: str | None
    dry_run_prepared_at: datetime | None
    live_preflight_payload_hash: str | None
    live_preflight_payload_key_version: str | None
    live_preflight_at: datetime | None
    live_preflight_status: str | None
    live_preflight_approval_queue_id: UUID | None
    gateway_idempotency_key_digest: str | None
    created_by_user_id: str
    created_at: datetime | None
    updated_at: datetime | None


@dataclass(frozen=True, slots=True)
class StoredRemovalRequestEvent:
    id: UUID
    request_id: UUID
    event_type: str
    actor: str
    event_payload_hash: str | None
    created_at: datetime | None


@dataclass(frozen=True, slots=True)
class RemovalRequestTransitionResult:
    request: StoredRemovalRequest
    event: StoredRemovalRequestEvent
    evidence_created: bool


@dataclass(frozen=True, slots=True)
class PrivacyGatewayDryRunResult:
    request: StoredRemovalRequest
    event: StoredRemovalRequestEvent
    gateway_path: str
    gateway_status: str
    egress_mode: str
    outbound_enabled: bool
    would_send: bool
    adapter_kind: str
    idempotency_key_digest: str
    dry_run_payload_hash: str
    prepared_at: datetime


@dataclass(frozen=True, slots=True)
class PrivacyGatewayLivePreflightResult:
    request: StoredRemovalRequest
    event: StoredRemovalRequestEvent
    gateway_path: str
    gateway_status: str
    egress_mode: str
    outbound_enabled: bool
    would_send: bool
    target_http_attempted: bool
    adapter_kind: str
    idempotency_key_digest: str
    live_preflight_payload_hash: str
    approval_queue_id: UUID
    prepared_at: datetime


class PrivacyAuthorizationLifecycleRepository:
    """Write/read P5-A lifecycle records through an RLS-bound connection."""

    def __init__(self, conn: asyncpg.Connection, crypto: PrivacyCrypto) -> None:
        self._conn = conn
        self._crypto = crypto

    async def create_authorization(
        self,
        *,
        subject_id: UUID,
        actor: str,
        authorization_type: str,
        signed_payload: dict[str, object],
        expires_at: datetime | None = None,
    ) -> StoredPrivacyAuthorization:
        actor = _clean_required(actor, "actor")
        authorization_type = _clean_required(
            authorization_type,
            "authorization_type",
        )
        if authorization_type not in _AUTHORIZATION_TYPES:
            raise PrivacyLifecycleTransitionError("authorization type invalid")
        if not signed_payload:
            raise PrivacyLifecycleTransitionError("signed authorization is required")

        async with self._conn.transaction():
            subject = await get_subject(self._conn, subject_id)
            if subject is None:
                raise PrivacyLifecycleNotFound("privacy subject not found")
            encrypted = self._crypto.encrypt_json_payload(
                {
                    "record_kind": "signed_privacy_authorization",
                    "authorization_type": authorization_type,
                    "subject_id": str(subject.id),
                    "subject_jurisdiction": subject.jurisdiction,
                    "actor": actor,
                    "signed_payload": signed_payload,
                    "outbound_enabled": False,
                    "captured_at": datetime.now(UTC).isoformat(),
                }
            )
            row = await self._conn.fetchrow(
                """
                INSERT INTO public.alpha_privacy_authorizations (
                    subject_id,
                    authorization_type,
                    status,
                    created_by_user_id,
                    authorization_payload_ciphertext,
                    authorization_payload_hash,
                    payload_key_version,
                    expires_at
                )
                VALUES ($1, $2, 'active', $3, $4, $5, $6, $7)
                RETURNING id, subject_id, authorization_type, status,
                          authorization_payload_hash, payload_key_version,
                          expires_at, revoked_at, created_at, updated_at
                """,
                subject.id,
                authorization_type,
                actor,
                encrypted.ciphertext,
                encrypted.payload_hash,
                encrypted.key_version,
                expires_at,
            )
        assert row is not None
        logger.info(
            "privacy_authorization_created subject_id=%s authorization_type=%s",
            subject_id,
            authorization_type,
        )
        return _row_to_authorization(row)

    async def list_authorizations(
        self,
        *,
        subject_id: UUID,
    ) -> list[StoredPrivacyAuthorization]:
        subject = await get_subject(self._conn, subject_id)
        if subject is None:
            raise PrivacyLifecycleNotFound("privacy subject not found")
        rows = await self._conn.fetch(
            """
            SELECT id, subject_id, authorization_type, status,
                   authorization_payload_hash, payload_key_version,
                   expires_at, revoked_at, created_at, updated_at
            FROM public.alpha_privacy_authorizations
            WHERE subject_id = $1
            ORDER BY created_at DESC, id DESC
            """,
            subject_id,
        )
        return [_row_to_authorization(row) for row in rows]

    async def create_request_for_action(
        self,
        *,
        action_id: UUID,
        actor: str,
        operator_note: str | None = None,
    ) -> StoredRemovalRequest:
        actor = _clean_required(actor, "actor")
        async with self._conn.transaction():
            existing = await self._request_for_action(action_id)
            if existing is not None:
                return existing

            action = await self._approved_action(action_id)
            if action is None:
                raise PrivacyLifecycleNotFound("approved privacy action not found")
            authorization = await self._active_authorization(action["subject_id"])
            if authorization is None:
                raise PrivacyLifecycleAuthorizationRequired(
                    "active privacy authorization required"
                )
            encrypted = self._crypto.encrypt_json_payload(
                {
                    "record_kind": "privacy_removal_request",
                    "workflow_version": "p5a-v1",
                    "action_id": str(action_id),
                    "subject_id": str(action["subject_id"]),
                    "target_id": str(action["target_id"]),
                    "authorization_id": str(authorization["id"]),
                    "draft_payload_hash": action["draft_payload_hash"],
                    "operator_note": _clean_optional(operator_note),
                    "outbound_enabled": False,
                    "queued_for": "future_gateway_executor",
                    "created_at": datetime.now(UTC).isoformat(),
                }
            )
            row = await self._conn.fetchrow(
                """
                INSERT INTO public.alpha_privacy_removal_requests (
                    subject_id,
                    target_id,
                    authorization_id,
                    action_id,
                    lifecycle_status,
                    request_payload_ciphertext,
                    request_payload_hash,
                    payload_key_version,
                    created_by_user_id
                )
                VALUES ($1, $2, $3, $4, 'queued', $5, $6, $7, $8)
                RETURNING id, subject_id, target_id, authorization_id, action_id,
                          lifecycle_status, request_payload_hash,
                          payload_key_version, current_evidence_count,
                          next_check_at, last_event_at, created_by_user_id,
                          created_at, updated_at
                """,
                action["subject_id"],
                action["target_id"],
                authorization["id"],
                action_id,
                encrypted.ciphertext,
                encrypted.payload_hash,
                encrypted.key_version,
                actor,
            )
            assert row is not None
            request = await self._request_by_id(row["id"])
            assert request is not None
            await self._append_event(
                request_id=request.id,
                event_type="created",
                actor=actor,
                payload=_event_payload(
                    self._crypto,
                    request_id=request.id,
                    event_type="created",
                    actor=actor,
                    details={
                        "action_id": str(action_id),
                        "authorization_id": str(authorization["id"]),
                        "outbound_enabled": False,
                    },
                ),
            )
        logger.info(
            "privacy_removal_request_created request_id=%s action_id=%s",
            request.id,
            action_id,
        )
        return request

    async def list_requests(
        self,
        *,
        subject_id: UUID | None = None,
        limit: int = 25,
    ) -> list[StoredRemovalRequest]:
        if limit < 1 or limit > 100:
            raise PrivacyLifecycleTransitionError("limit must be between 1 and 100")
        args: list[object] = [limit]
        where = ""
        if subject_id is not None:
            subject = await get_subject(self._conn, subject_id)
            if subject is None:
                raise PrivacyLifecycleNotFound("privacy subject not found")
            where = "WHERE request.subject_id = $2"
            args.append(subject_id)
        rows = await self._conn.fetch(
            f"""
            SELECT
                request.id, request.subject_id, request.target_id,
                request.authorization_id, request.action_id,
                request.lifecycle_status, request.request_payload_hash,
                request.payload_key_version, request.dry_run_payload_hash,
                request.dry_run_payload_key_version,
                request.dry_run_prepared_at,
                request.live_preflight_payload_hash,
                request.live_preflight_payload_key_version,
                request.live_preflight_at,
                request.live_preflight_status,
                request.live_preflight_approval_queue_id,
                request.gateway_idempotency_key_digest,
                request.current_evidence_count, request.next_check_at,
                request.last_event_at,
                request.created_by_user_id, request.created_at,
                request.updated_at,
                target.name AS target_name,
                target.category AS target_category,
                target.opt_out_method AS target_opt_out_method
            FROM public.alpha_privacy_removal_requests AS request
            JOIN public.alpha_privacy_targets_cache AS target
              ON target.id = request.target_id
            {where}
            ORDER BY request.created_at DESC, request.id DESC
            LIMIT $1
            """,
            *args,
        )
        return [_row_to_request(row) for row in rows]

    async def transition_request(
        self,
        *,
        request_id: UUID,
        actor: str,
        lifecycle_status: str,
        operator_note: str | None = None,
        evidence_reference: str | None = None,
        next_check_at: datetime | None = None,
    ) -> RemovalRequestTransitionResult:
        actor = _clean_required(actor, "actor")
        lifecycle_status = _clean_required(lifecycle_status, "lifecycle_status")
        if lifecycle_status not in _REQUEST_STATUSES:
            raise PrivacyLifecycleTransitionError("request lifecycle status invalid")

        async with self._conn.transaction():
            current = await self._request_by_id(request_id)
            if current is None:
                raise PrivacyLifecycleNotFound("privacy removal request not found")
            if lifecycle_status not in _ALLOWED_TRANSITIONS[current.lifecycle_status]:
                raise PrivacyLifecycleTransitionError(
                    "privacy removal request transition invalid"
                )

            event_payload = _event_payload(
                self._crypto,
                request_id=request_id,
                event_type=lifecycle_status,
                actor=actor,
                details={
                    "from_status": current.lifecycle_status,
                    "to_status": lifecycle_status,
                    "operator_note": _clean_optional(operator_note),
                    "evidence_reference_present": bool(
                        _clean_optional(evidence_reference)
                    ),
                    "next_check_at": (
                        next_check_at.isoformat() if next_check_at else None
                    ),
                    "outbound_enabled": False,
                },
            )
            evidence_created = False
            if _clean_optional(evidence_reference):
                await self._insert_evidence(
                    request=current,
                    actor=actor,
                    lifecycle_status=lifecycle_status,
                    evidence_reference=evidence_reference,
                )
                evidence_created = True

            row = await self._conn.fetchrow(
                """
                UPDATE public.alpha_privacy_removal_requests AS request
                SET lifecycle_status = $2,
                    next_check_at = $3,
                    last_event_at = NOW(),
                    current_evidence_count = current_evidence_count + $4
                WHERE request.id = $1
                RETURNING request.id, request.subject_id, request.target_id,
                          request.authorization_id, request.action_id,
                          request.lifecycle_status, request.request_payload_hash,
                          request.payload_key_version,
                          request.current_evidence_count, request.next_check_at,
                          request.last_event_at, request.created_by_user_id,
                          request.created_at, request.updated_at
                """,
                request_id,
                lifecycle_status,
                next_check_at,
                1 if evidence_created else 0,
            )
            assert row is not None
            updated = await self._request_by_id(row["id"])
            assert updated is not None
            event = await self._append_event(
                request_id=request_id,
                event_type=lifecycle_status,
                actor=actor,
                payload=event_payload,
            )
        logger.info(
            "privacy_removal_request_transition request_id=%s status=%s evidence=%s",
            request_id,
            lifecycle_status,
            evidence_created,
        )
        return RemovalRequestTransitionResult(
            request=updated,
            event=event,
            evidence_created=evidence_created,
        )

    async def prepare_gateway_dry_run(
        self,
        *,
        request_id: UUID,
        actor: str,
        gateway_call: GatewayDryRunCaller = call_gateway_proxy,
    ) -> PrivacyGatewayDryRunResult:
        actor = _clean_required(actor, "actor")

        current = await self._request_by_id(request_id)
        if current is None:
            raise PrivacyLifecycleNotFound("privacy removal request not found")
        if current.lifecycle_status not in _DRY_RUN_ALLOWED_STATUSES:
            raise PrivacyLifecycleTransitionError(
                "privacy removal request dry-run invalid"
            )

        binding = await self._approval_binding(current.action_id)
        prepared_at = datetime.now(UTC)
        idempotency_key_digest = self._crypto.digest_value(
            "privacy_gateway_idempotency_key",
            f"{request_id}:dry-run:v1",
        )
        envelope = _gateway_dry_run_envelope(
            request=current,
            binding=binding,
            idempotency_key_digest=idempotency_key_digest,
            prepared_at=prepared_at,
        )
        try:
            gateway_response = await gateway_call(
                _GATEWAY_DRY_RUN_PROXY_PATH,
                envelope,
                timeout_s=15,
            )
        except GatewayEgressError as exc:
            raise PrivacyLifecycleGatewayError(
                "privacy gateway dry-run unavailable"
            ) from exc

        _validate_gateway_dry_run_response(
            gateway_response,
            request=current,
            idempotency_key_digest=idempotency_key_digest,
        )
        gateway_status = str(gateway_response.get("status", "unknown"))
        outbound_enabled = bool(gateway_response.get("outbound_enabled"))
        would_send = bool(gateway_response.get("would_send"))

        async with self._conn.transaction():
            fresh = await self._request_by_id(request_id)
            if fresh is None:
                raise PrivacyLifecycleNotFound("privacy removal request not found")
            if fresh.lifecycle_status not in _DRY_RUN_ALLOWED_STATUSES:
                raise PrivacyLifecycleTransitionError(
                    "privacy removal request dry-run invalid"
                )
            encrypted = self._crypto.encrypt_json_payload(
                {
                    "record_kind": "privacy_gateway_dry_run",
                    "workflow_version": _GATEWAY_DRY_RUN_SCHEMA,
                    "request_id": str(request_id),
                    "gateway_path": _GATEWAY_DRY_RUN_HTTP_PATH,
                    "gateway_response": gateway_response,
                    "envelope": envelope,
                    "outbound_enabled": False,
                    "would_send": False,
                    "prepared_at": prepared_at.isoformat(),
                }
            )
            row = await self._conn.fetchrow(
                """
                UPDATE public.alpha_privacy_removal_requests AS request
                SET dry_run_payload_ciphertext = $2,
                    dry_run_payload_hash = $3,
                    dry_run_payload_key_version = $4,
                    dry_run_prepared_at = $5,
                    gateway_idempotency_key_digest = $6,
                    last_event_at = NOW()
                WHERE request.id = $1
                RETURNING request.id
                """,
                request_id,
                encrypted.ciphertext,
                encrypted.payload_hash,
                encrypted.key_version,
                prepared_at,
                idempotency_key_digest,
            )
            assert row is not None
            updated = await self._request_by_id(request_id)
            assert updated is not None
            event = await self._append_event(
                request_id=request_id,
                event_type="dry_run_prepared",
                actor=actor,
                payload=_event_payload(
                    self._crypto,
                    request_id=request_id,
                    event_type="dry_run_prepared",
                    actor=actor,
                    details={
                        "gateway_path": _GATEWAY_DRY_RUN_HTTP_PATH,
                        "gateway_status": gateway_status,
                        "egress_mode": _GATEWAY_DRY_RUN_MODE,
                        "adapter_kind": _adapter_kind(fresh.target_opt_out_method),
                        "dry_run_payload_hash": encrypted.payload_hash,
                        "idempotency_key_digest": idempotency_key_digest,
                        "outbound_enabled": False,
                        "would_send": False,
                    },
                ),
            )
        logger.info(
            "privacy_gateway_dry_run_prepared request_id=%s target_id=%s",
            request_id,
            updated.target_id,
        )
        return PrivacyGatewayDryRunResult(
            request=updated,
            event=event,
            gateway_path=_GATEWAY_DRY_RUN_HTTP_PATH,
            gateway_status=gateway_status,
            egress_mode=_GATEWAY_DRY_RUN_MODE,
            outbound_enabled=outbound_enabled,
            would_send=would_send,
            adapter_kind=_adapter_kind(updated.target_opt_out_method),
            idempotency_key_digest=idempotency_key_digest,
            dry_run_payload_hash=encrypted.payload_hash,
            prepared_at=prepared_at,
        )

    async def prepare_gateway_live_preflight(
        self,
        *,
        request_id: UUID,
        actor: str,
        gateway_call: GatewayDryRunCaller = call_gateway_proxy,
    ) -> PrivacyGatewayLivePreflightResult:
        actor = _clean_required(actor, "actor")

        current = await self._request_by_id(request_id)
        if current is None:
            raise PrivacyLifecycleNotFound("privacy removal request not found")
        if current.lifecycle_status not in _LIVE_PREFLIGHT_ALLOWED_STATUSES:
            raise PrivacyLifecycleTransitionError(
                "privacy removal request live preflight invalid"
            )
        if current.target_id != _LIVE_PREFLIGHT_TARGET_ID:
            raise PrivacyLifecycleTransitionError(
                "privacy live preflight target not allowed"
            )
        if current.target_opt_out_method != "web_form":
            raise PrivacyLifecycleTransitionError(
                "privacy live preflight adapter not available"
            )
        if not current.dry_run_payload_hash:
            raise PrivacyLifecycleTransitionError(
                "privacy gateway dry-run proof required"
            )

        binding = await self._fresh_approval_binding(current.action_id)
        prepared_at = datetime.now(UTC)
        idempotency_key_digest = self._crypto.digest_value(
            "privacy_gateway_idempotency_key",
            f"{request_id}:live-preflight:{binding['approval_queue_id']}:v1",
        )
        envelope = _gateway_live_preflight_envelope(
            request=current,
            binding=binding,
            idempotency_key_digest=idempotency_key_digest,
            prepared_at=prepared_at,
        )
        try:
            gateway_response = await gateway_call(
                _GATEWAY_LIVE_PREFLIGHT_PROXY_PATH,
                envelope,
                timeout_s=20,
            )
        except GatewayEgressError as exc:
            raise PrivacyLifecycleGatewayError(
                "privacy gateway live preflight unavailable"
            ) from exc

        _validate_gateway_live_preflight_response(
            gateway_response,
            request=current,
            idempotency_key_digest=idempotency_key_digest,
        )
        gateway_status = str(gateway_response.get("status", "unknown"))
        outbound_enabled = bool(gateway_response.get("outbound_enabled"))
        would_send = bool(gateway_response.get("would_send"))
        target_http_attempted = bool(gateway_response.get("target_http_attempted"))
        event_type = _live_preflight_event_type(gateway_status)
        approval_queue_id = UUID(str(binding["approval_queue_id"]))

        async with self._conn.transaction():
            fresh = await self._request_by_id(request_id)
            if fresh is None:
                raise PrivacyLifecycleNotFound("privacy removal request not found")
            if fresh.lifecycle_status not in _LIVE_PREFLIGHT_ALLOWED_STATUSES:
                raise PrivacyLifecycleTransitionError(
                    "privacy removal request live preflight invalid"
                )
            if fresh.dry_run_payload_hash != current.dry_run_payload_hash:
                raise PrivacyLifecycleTransitionError(
                    "privacy gateway dry-run proof changed"
                )
            encrypted = self._crypto.encrypt_json_payload(
                {
                    "record_kind": "privacy_gateway_live_preflight",
                    "workflow_version": _GATEWAY_LIVE_PREFLIGHT_SCHEMA,
                    "request_id": str(request_id),
                    "gateway_path": _GATEWAY_LIVE_PREFLIGHT_HTTP_PATH,
                    "gateway_response": gateway_response,
                    "envelope": envelope,
                    "target_id": _LIVE_PREFLIGHT_TARGET_ID,
                    "allowed_effects": [_LIVE_PREFLIGHT_ALLOWED_EFFECT],
                    "blocked_effects": list(_LIVE_PREFLIGHT_REQUIRED_BLOCKED),
                    "would_send": False,
                    "prepared_at": prepared_at.isoformat(),
                }
            )
            row = await self._conn.fetchrow(
                """
                UPDATE public.alpha_privacy_removal_requests AS request
                SET live_preflight_payload_ciphertext = $2,
                    live_preflight_payload_hash = $3,
                    live_preflight_payload_key_version = $4,
                    live_preflight_at = $5,
                    live_preflight_status = $6,
                    live_preflight_approval_queue_id = $7,
                    gateway_idempotency_key_digest = $8,
                    last_event_at = NOW()
                WHERE request.id = $1
                RETURNING request.id
                """,
                request_id,
                encrypted.ciphertext,
                encrypted.payload_hash,
                encrypted.key_version,
                prepared_at,
                gateway_status,
                approval_queue_id,
                idempotency_key_digest,
            )
            assert row is not None
            updated = await self._request_by_id(request_id)
            assert updated is not None
            event = await self._append_event(
                request_id=request_id,
                event_type=event_type,
                actor=actor,
                payload=_event_payload(
                    self._crypto,
                    request_id=request_id,
                    event_type=event_type,
                    actor=actor,
                    details={
                        "gateway_path": _GATEWAY_LIVE_PREFLIGHT_HTTP_PATH,
                        "gateway_status": gateway_status,
                        "egress_mode": _GATEWAY_LIVE_PREFLIGHT_MODE,
                        "adapter_kind": _live_adapter_kind(fresh.target_id),
                        "live_preflight_payload_hash": encrypted.payload_hash,
                        "approval_queue_id": str(approval_queue_id),
                        "idempotency_key_digest": idempotency_key_digest,
                        "outbound_enabled": outbound_enabled,
                        "would_send": False,
                        "target_http_attempted": target_http_attempted,
                    },
                ),
            )
        logger.info(
            "privacy_gateway_live_preflight request_id=%s target_id=%s status=%s",
            request_id,
            updated.target_id,
            gateway_status,
        )
        return PrivacyGatewayLivePreflightResult(
            request=updated,
            event=event,
            gateway_path=_GATEWAY_LIVE_PREFLIGHT_HTTP_PATH,
            gateway_status=gateway_status,
            egress_mode=_GATEWAY_LIVE_PREFLIGHT_MODE,
            outbound_enabled=outbound_enabled,
            would_send=would_send,
            target_http_attempted=target_http_attempted,
            adapter_kind=_live_adapter_kind(updated.target_id),
            idempotency_key_digest=idempotency_key_digest,
            live_preflight_payload_hash=encrypted.payload_hash,
            approval_queue_id=approval_queue_id,
            prepared_at=prepared_at,
        )

    async def _request_for_action(
        self,
        action_id: UUID,
    ) -> StoredRemovalRequest | None:
        row = await self._conn.fetchrow(
            """
            SELECT
                request.id, request.subject_id, request.target_id,
                request.authorization_id, request.action_id,
                request.lifecycle_status, request.request_payload_hash,
                request.payload_key_version, request.dry_run_payload_hash,
                request.dry_run_payload_key_version,
                request.dry_run_prepared_at,
                request.live_preflight_payload_hash,
                request.live_preflight_payload_key_version,
                request.live_preflight_at,
                request.live_preflight_status,
                request.live_preflight_approval_queue_id,
                request.gateway_idempotency_key_digest,
                request.current_evidence_count, request.next_check_at,
                request.last_event_at,
                request.created_by_user_id, request.created_at,
                request.updated_at,
                target.name AS target_name,
                target.category AS target_category,
                target.opt_out_method AS target_opt_out_method
            FROM public.alpha_privacy_removal_requests AS request
            JOIN public.alpha_privacy_targets_cache AS target
              ON target.id = request.target_id
            WHERE request.action_id = $1
            """,
            action_id,
        )
        return _row_to_request(row) if row else None

    async def _request_by_id(
        self,
        request_id: UUID,
    ) -> StoredRemovalRequest | None:
        row = await self._conn.fetchrow(
            """
            SELECT
                request.id, request.subject_id, request.target_id,
                request.authorization_id, request.action_id,
                request.lifecycle_status, request.request_payload_hash,
                request.payload_key_version, request.dry_run_payload_hash,
                request.dry_run_payload_key_version,
                request.dry_run_prepared_at,
                request.live_preflight_payload_hash,
                request.live_preflight_payload_key_version,
                request.live_preflight_at,
                request.live_preflight_status,
                request.live_preflight_approval_queue_id,
                request.gateway_idempotency_key_digest,
                request.current_evidence_count, request.next_check_at,
                request.last_event_at,
                request.created_by_user_id, request.created_at,
                request.updated_at,
                target.name AS target_name,
                target.category AS target_category,
                target.opt_out_method AS target_opt_out_method
            FROM public.alpha_privacy_removal_requests AS request
            JOIN public.alpha_privacy_targets_cache AS target
              ON target.id = request.target_id
            WHERE request.id = $1
            """,
            request_id,
        )
        return _row_to_request(row) if row else None

    async def _approved_action(self, action_id: UUID):
        return await self._conn.fetchrow(
            """
            SELECT id, subject_id, target_id, draft_payload_hash
            FROM public.alpha_privacy_actions
            WHERE id = $1
              AND status IN ('approved', 'sent', 'confirmed')
              AND approval_queue_id IS NOT NULL
            """,
            action_id,
        )

    async def _active_authorization(self, subject_id: UUID):
        return await self._conn.fetchrow(
            """
            SELECT id
            FROM public.alpha_privacy_authorizations
            WHERE subject_id = $1
              AND status = 'active'
              AND authorization_type IN (
                  'agent_authorization',
                  'guardian_authorization',
                  'custom_removal'
              )
              AND (expires_at IS NULL OR expires_at > NOW())
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            subject_id,
        )

    async def _approval_binding(self, action_id: UUID | None) -> dict[str, object]:
        if action_id is None:
            return {
                "approval_required": True,
                "approval_queue_id": None,
                "approval_tier": None,
                "approved_action_payload_hash": None,
            }
        row = await self._conn.fetchrow(
            """
            SELECT approval_queue_id, approval_tier, draft_payload_hash
            FROM public.alpha_privacy_actions
            WHERE id = $1
            """,
            action_id,
        )
        if row is None:
            raise PrivacyLifecycleNotFound("approved privacy action not found")
        return {
            "approval_required": True,
            "approval_queue_id": (
                str(row["approval_queue_id"]) if row["approval_queue_id"] else None
            ),
            "approval_tier": row["approval_tier"],
            "approved_action_payload_hash": row["draft_payload_hash"],
        }

    async def _fresh_approval_binding(
        self, action_id: UUID | None
    ) -> dict[str, object]:
        if action_id is None:
            raise PrivacyLifecycleTransitionError("fresh approval binding required")
        row = await self._conn.fetchrow(
            """
            SELECT
                action.approval_queue_id,
                action.approval_tier,
                action.draft_payload_hash,
                action.status AS action_status,
                queue.status AS approval_status,
                queue.parameters_hash AS approval_parameters_hash,
                queue.decided_at,
                queue.expires_at
            FROM public.alpha_privacy_actions AS action
            JOIN public.alpha_approval_queue AS queue
              ON queue.id = action.approval_queue_id
            WHERE action.id = $1
            """,
            action_id,
        )
        if row is None:
            raise PrivacyLifecycleNotFound("approved privacy action not found")
        decided_at = _coerce_utc(row["decided_at"])
        expires_at = _coerce_utc(row["expires_at"])
        now = datetime.now(UTC)
        if row["action_status"] != "approved":
            raise PrivacyLifecycleTransitionError(
                "fresh approval action status invalid"
            )
        if row["approval_status"] != "approved":
            raise PrivacyLifecycleTransitionError("fresh approval is not approved")
        if decided_at is None:
            raise PrivacyLifecycleTransitionError("fresh approval decision missing")
        if now - decided_at > _LIVE_APPROVAL_MAX_AGE:
            raise PrivacyLifecycleTransitionError("fresh approval window expired")
        if expires_at is not None and expires_at <= now:
            raise PrivacyLifecycleTransitionError("fresh approval expired")
        return {
            "approval_required": True,
            "approval_queue_id": str(row["approval_queue_id"]),
            "approval_tier": row["approval_tier"],
            "approval_status": row["approval_status"],
            "approval_decided_at": decided_at.isoformat(),
            "approval_expires_at": expires_at.isoformat() if expires_at else None,
            "approval_parameters_hash": row["approval_parameters_hash"],
            "approved_action_payload_hash": row["draft_payload_hash"],
            "freshness_window_seconds": int(_LIVE_APPROVAL_MAX_AGE.total_seconds()),
        }

    async def _insert_evidence(
        self,
        *,
        request: StoredRemovalRequest,
        actor: str,
        lifecycle_status: str,
        evidence_reference: str | None,
    ) -> None:
        payload = self._crypto.encrypt_json_payload(
            {
                "record_kind": "privacy_removal_lifecycle_proof",
                "request_id": str(request.id),
                "action_id": str(request.action_id) if request.action_id else None,
                "target_id": request.target_id,
                "lifecycle_status": lifecycle_status,
                "evidence_reference": _clean_optional(evidence_reference),
                "outbound_enabled": False,
                "captured_at": datetime.now(UTC).isoformat(),
            }
        )
        await self._conn.execute(
            """
            INSERT INTO public.alpha_privacy_evidence_items (
                subject_id,
                target_id,
                action_id,
                removal_request_id,
                evidence_type,
                status,
                evidence_payload_ciphertext,
                evidence_payload_hash,
                payload_key_version,
                captured_by_user_id
            )
            VALUES (
                $1, $2, $3, $4, $5, 'captured', $6, $7, $8, $9
            )
            """,
            request.subject_id,
            request.target_id,
            request.action_id,
            request.id,
            _evidence_type_for_status(lifecycle_status),
            payload.ciphertext,
            payload.payload_hash,
            payload.key_version,
            actor,
        )

    async def _append_event(
        self,
        *,
        request_id: UUID,
        event_type: str,
        actor: str,
        payload: EncryptedPayload | None,
    ) -> StoredRemovalRequestEvent:
        row = await self._conn.fetchrow(
            """
            INSERT INTO public.alpha_privacy_removal_request_events (
                request_id,
                event_type,
                actor,
                event_payload_ciphertext,
                event_payload_hash
            )
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id, request_id, event_type, actor, event_payload_hash,
                      created_at
            """,
            request_id,
            event_type,
            actor,
            payload.ciphertext if payload else None,
            payload.payload_hash if payload else None,
        )
        assert row is not None
        return _row_to_request_event(row)


def _event_payload(
    crypto: PrivacyCrypto,
    *,
    request_id: UUID,
    event_type: str,
    actor: str,
    details: dict[str, object],
) -> EncryptedPayload:
    return crypto.encrypt_json_payload(
        {
            "record_kind": "privacy_removal_request_event",
            "workflow_version": "p5a-v1",
            "request_id": str(request_id),
            "event_type": event_type,
            "actor": actor,
            "details": details,
            "created_at": datetime.now(UTC).isoformat(),
        }
    )


def _gateway_dry_run_envelope(
    *,
    request: StoredRemovalRequest,
    binding: dict[str, object],
    idempotency_key_digest: str,
    prepared_at: datetime,
) -> dict[str, object]:
    return {
        "schema_version": _GATEWAY_DRY_RUN_SCHEMA,
        "operation": "privacy.removal.submit",
        "mode": "dry_run",
        "egress_owner": "gateway",
        "egress_mode": _GATEWAY_DRY_RUN_MODE,
        "outbound_enabled": False,
        "would_send": False,
        "request_id": str(request.id),
        "subject_id": str(request.subject_id),
        "target_id": request.target_id,
        "target_category": request.target_category,
        "target_opt_out_method": request.target_opt_out_method,
        "adapter_kind": _adapter_kind(request.target_opt_out_method),
        "authorization_id": str(request.authorization_id),
        "action_id": str(request.action_id) if request.action_id else None,
        "request_payload_hash": request.request_payload_hash,
        "idempotency_key_digest": idempotency_key_digest,
        "approval_binding": binding,
        "allowed_effects": [],
        "blocked_effects": [
            "public_http",
            "browser_automation",
            "email_send",
            "sms_send",
            "broker_form_submit",
        ],
        "prepared_at": prepared_at.isoformat(),
    }


def _gateway_live_preflight_envelope(
    *,
    request: StoredRemovalRequest,
    binding: dict[str, object],
    idempotency_key_digest: str,
    prepared_at: datetime,
) -> dict[str, object]:
    return {
        "schema_version": _GATEWAY_LIVE_PREFLIGHT_SCHEMA,
        "operation": "privacy.removal.live_preflight",
        "mode": "live_preflight",
        "egress_owner": "gateway",
        "egress_mode": _GATEWAY_LIVE_PREFLIGHT_MODE,
        "live_enabled_requested": True,
        "request_id": str(request.id),
        "subject_id": str(request.subject_id),
        "target_id": request.target_id,
        "target_category": request.target_category,
        "target_opt_out_method": request.target_opt_out_method,
        "adapter_kind": _live_adapter_kind(request.target_id),
        "authorization_id": str(request.authorization_id),
        "action_id": str(request.action_id) if request.action_id else None,
        "request_payload_hash": request.request_payload_hash,
        "dry_run_payload_hash": request.dry_run_payload_hash,
        "idempotency_key_digest": idempotency_key_digest,
        "approval_binding": binding,
        "allowed_effects": [_LIVE_PREFLIGHT_ALLOWED_EFFECT],
        "blocked_effects": list(_LIVE_PREFLIGHT_REQUIRED_BLOCKED),
        "prepared_at": prepared_at.isoformat(),
    }


def _validate_gateway_dry_run_response(
    response: dict[str, object],
    *,
    request: StoredRemovalRequest,
    idempotency_key_digest: str,
) -> None:
    if response.get("status") != "dry_run_ready":
        raise PrivacyLifecycleGatewayError("privacy gateway dry-run rejected")
    if response.get("request_id") != str(request.id):
        raise PrivacyLifecycleGatewayError("privacy gateway dry-run request mismatch")
    if response.get("target_id") != request.target_id:
        raise PrivacyLifecycleGatewayError("privacy gateway dry-run target mismatch")
    if response.get("idempotency_key_digest") != idempotency_key_digest:
        raise PrivacyLifecycleGatewayError(
            "privacy gateway dry-run idempotency mismatch"
        )
    if response.get("outbound_enabled") is not False:
        raise PrivacyLifecycleGatewayError("privacy gateway dry-run enabled outbound")
    if response.get("would_send") is not False:
        raise PrivacyLifecycleGatewayError("privacy gateway dry-run would send")


def _validate_gateway_live_preflight_response(
    response: dict[str, object],
    *,
    request: StoredRemovalRequest,
    idempotency_key_digest: str,
) -> None:
    status = response.get("status")
    if status not in _LIVE_PREFLIGHT_GATEWAY_STATUSES:
        raise PrivacyLifecycleGatewayError("privacy gateway live preflight rejected")
    if response.get("request_id") != str(request.id):
        raise PrivacyLifecycleGatewayError(
            "privacy gateway live preflight request mismatch"
        )
    if response.get("target_id") != request.target_id:
        raise PrivacyLifecycleGatewayError(
            "privacy gateway live preflight target mismatch"
        )
    if response.get("idempotency_key_digest") != idempotency_key_digest:
        raise PrivacyLifecycleGatewayError(
            "privacy gateway live preflight idempotency mismatch"
        )
    if response.get("would_send") is not False:
        raise PrivacyLifecycleGatewayError("privacy gateway live preflight would send")
    if status == "live_disabled":
        if response.get("outbound_enabled") is not False:
            raise PrivacyLifecycleGatewayError(
                "privacy gateway live preflight disabled but outbound"
            )
        if response.get("target_http_attempted") is not False:
            raise PrivacyLifecycleGatewayError(
                "privacy gateway live preflight disabled but attempted target"
            )
    else:
        if response.get("outbound_enabled") is not True:
            raise PrivacyLifecycleGatewayError(
                "privacy gateway live preflight missing outbound proof"
            )
        if response.get("target_http_attempted") is not True:
            raise PrivacyLifecycleGatewayError(
                "privacy gateway live preflight missing target attempt"
            )
    if response.get("adapter_kind") != _live_adapter_kind(request.target_id):
        raise PrivacyLifecycleGatewayError(
            "privacy gateway live preflight adapter mismatch"
        )


def _adapter_kind(opt_out_method: str) -> str:
    if opt_out_method == "web_form":
        return "gateway_web_form_dry_run"
    if opt_out_method == "email":
        return "gateway_email_dry_run"
    if opt_out_method == "api":
        return "gateway_api_dry_run"
    return "manual_only"


def _live_adapter_kind(target_id: str) -> str:
    if target_id == _LIVE_PREFLIGHT_TARGET_ID:
        return "beenverified_web_form_live_preflight"
    return "unsupported_live_preflight"


def _live_preflight_event_type(gateway_status: str) -> str:
    if gateway_status == "live_preflight_passed":
        return "live_preflight_passed"
    if gateway_status == "live_preflight_failed":
        return "live_preflight_failed"
    return "live_preflight_blocked"


def _coerce_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _clean_required(value: str, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise PrivacyLifecycleTransitionError(f"{field_name} is required")
    return cleaned


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _evidence_type_for_status(status: str) -> str:
    if status == "completed":
        return "verification"
    if status in {"acknowledged", "failed", "escalated"}:
        return "broker_reply"
    return "work_receipt"


def _row_to_authorization(row) -> StoredPrivacyAuthorization:
    return StoredPrivacyAuthorization(
        id=row["id"],
        subject_id=row["subject_id"],
        authorization_type=row["authorization_type"],
        status=row["status"],
        authorization_payload_hash=row["authorization_payload_hash"],
        payload_key_version=row["payload_key_version"],
        expires_at=row["expires_at"],
        revoked_at=row["revoked_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_request(row) -> StoredRemovalRequest:
    return StoredRemovalRequest(
        id=row["id"],
        subject_id=row["subject_id"],
        target_id=row["target_id"],
        target_name=row["target_name"],
        target_category=row["target_category"],
        authorization_id=row["authorization_id"],
        action_id=row["action_id"],
        lifecycle_status=row["lifecycle_status"],
        request_payload_hash=row["request_payload_hash"],
        payload_key_version=row["payload_key_version"],
        target_opt_out_method=row["target_opt_out_method"],
        current_evidence_count=int(row["current_evidence_count"]),
        next_check_at=row["next_check_at"],
        last_event_at=row["last_event_at"],
        dry_run_payload_hash=row["dry_run_payload_hash"],
        dry_run_payload_key_version=row["dry_run_payload_key_version"],
        dry_run_prepared_at=row["dry_run_prepared_at"],
        live_preflight_payload_hash=row["live_preflight_payload_hash"],
        live_preflight_payload_key_version=row["live_preflight_payload_key_version"],
        live_preflight_at=row["live_preflight_at"],
        live_preflight_status=row["live_preflight_status"],
        live_preflight_approval_queue_id=row["live_preflight_approval_queue_id"],
        gateway_idempotency_key_digest=row["gateway_idempotency_key_digest"],
        created_by_user_id=row["created_by_user_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_request_event(row) -> StoredRemovalRequestEvent:
    return StoredRemovalRequestEvent(
        id=row["id"],
        request_id=row["request_id"],
        event_type=row["event_type"],
        actor=row["actor"],
        event_payload_hash=row["event_payload_hash"],
        created_at=row["created_at"],
    )


_AUTHORIZATION_TYPES = {
    "agent_authorization",
    "guardian_authorization",
    "custom_removal",
    "search_deindex",
    "public_record_triage",
}
_REQUEST_STATUSES = {
    "draft",
    "approved",
    "queued",
    "sent",
    "acknowledged",
    "monitoring",
    "completed",
    "failed",
    "escalated",
    "blocked",
}
_ALLOWED_TRANSITIONS = {
    "draft": {"approved", "blocked"},
    "approved": {"queued", "blocked"},
    "queued": {"sent", "blocked", "escalated"},
    "sent": {"acknowledged", "monitoring", "completed", "failed", "escalated"},
    "acknowledged": {"monitoring", "completed", "failed", "escalated"},
    "monitoring": {"queued", "completed", "failed", "escalated"},
    "completed": set(),
    "failed": set(),
    "escalated": set(),
    "blocked": set(),
}
_DRY_RUN_ALLOWED_STATUSES = {"approved", "queued"}
_GATEWAY_DRY_RUN_SCHEMA = "privacy_gateway_dry_run.v1"
_GATEWAY_DRY_RUN_MODE = "gateway_dry_run"
_GATEWAY_DRY_RUN_PROXY_PATH = "privacy/removal/dry-run"
_GATEWAY_DRY_RUN_HTTP_PATH = "/v1/cloud/privacy/removal/dry-run"
_LIVE_PREFLIGHT_ALLOWED_STATUSES = {"queued"}
_LIVE_PREFLIGHT_GATEWAY_STATUSES = {
    "live_disabled",
    "live_preflight_passed",
    "live_preflight_failed",
}
_LIVE_PREFLIGHT_TARGET_ID = "beenverified"
_LIVE_PREFLIGHT_ALLOWED_EFFECT = "target_http_get"
_LIVE_PREFLIGHT_REQUIRED_BLOCKED = (
    "browser_automation",
    "email_send",
    "sms_send",
    "broker_form_submit",
    "pii_payload_submit",
)
_LIVE_APPROVAL_MAX_AGE = timedelta(minutes=15)
_GATEWAY_LIVE_PREFLIGHT_SCHEMA = "privacy_gateway_live_preflight.v1"
_GATEWAY_LIVE_PREFLIGHT_MODE = "gateway_live_preflight"
_GATEWAY_LIVE_PREFLIGHT_PROXY_PATH = "privacy/removal/live-preflight"
_GATEWAY_LIVE_PREFLIGHT_HTTP_PATH = "/v1/cloud/privacy/removal/live-preflight"
