from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from brain.agents.privacy_scrub.crypto import PrivacyCrypto, PrivacyCryptoConfig
from brain.agents.privacy_scrub.lifecycle import (
    PrivacyAuthorizationLifecycleRepository,
    PrivacyLifecycleAuthorizationRequired,
    PrivacyLifecycleTransitionError,
)
from brain.agents.privacy_scrub.subjects import Role, SubjectStatus


def _crypto() -> PrivacyCrypto:
    return PrivacyCrypto(
        PrivacyCryptoConfig(
            digest_key="test-digest-key",
            digest_key_version="digest-v1",
            payload_key="test-payload-key",
            payload_key_version="payload-v1",
        )
    )


def test_lifecycle_module_uses_gateway_proxy_not_direct_outbound() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "brain"
        / "agents"
        / "privacy_scrub"
        / "lifecycle.py"
    ).read_text(encoding="utf-8")
    assert "call_gateway_proxy" in source
    forbidden = (
        "import requests",
        "from requests",
        "import httpx",
        "from httpx",
        "import smtplib",
        "from smtplib",
        "import selenium",
        "from selenium",
        "import playwright",
        "from playwright",
    )
    for token in forbidden:
        assert token not in source


@pytest.mark.asyncio
async def test_create_authorization_stores_encrypted_signed_payload() -> None:
    subject_id = uuid4()
    conn = _FakeLifecycleConn(subject_id=subject_id)

    authorization = await PrivacyAuthorizationLifecycleRepository(
        conn,  # type: ignore[arg-type]
        _crypto(),
    ).create_authorization(
        subject_id=subject_id,
        actor="ken",
        authorization_type="agent_authorization",
        signed_payload={
            "signature_attestation": "signed by operator",
            "raw_identifier": "never-store-this-plaintext",
        },
    )

    assert authorization.subject_id == subject_id
    assert authorization.status == "active"
    assert authorization.authorization_payload_hash.startswith("sha256:")
    assert len(conn.authorization_inserts) == 1
    assert "never-store-this-plaintext" not in repr(conn.authorization_inserts)


@pytest.mark.asyncio
async def test_create_removal_request_requires_active_authorization() -> None:
    conn = _FakeLifecycleConn(active_authorization=False)

    with pytest.raises(PrivacyLifecycleAuthorizationRequired):
        await PrivacyAuthorizationLifecycleRepository(
            conn,  # type: ignore[arg-type]
            _crypto(),
        ).create_request_for_action(
            action_id=conn.action_id,
            actor="ken",
            operator_note="queue this after approval",
        )

    assert conn.request_inserts == []


@pytest.mark.asyncio
async def test_create_removal_request_queues_approved_action_without_outbound() -> None:
    conn = _FakeLifecycleConn()

    request = await PrivacyAuthorizationLifecycleRepository(
        conn,  # type: ignore[arg-type]
        _crypto(),
    ).create_request_for_action(
        action_id=conn.action_id,
        actor="ken",
        operator_note="do not leak this note",
    )

    assert request.action_id == conn.action_id
    assert request.lifecycle_status == "queued"
    assert request.request_payload_hash.startswith("sha256:")
    assert len(conn.request_inserts) == 1
    assert len(conn.event_inserts) == 1
    assert conn.evidence_inserts == []
    assert "do not leak this note" not in repr(conn.request_inserts)
    assert "outbound_enabled" not in repr(conn.request_inserts)


@pytest.mark.asyncio
async def test_transition_removal_request_completed_attaches_proof() -> None:
    conn = _FakeLifecycleConn(request_status="sent")

    result = await PrivacyAuthorizationLifecycleRepository(
        conn,  # type: ignore[arg-type]
        _crypto(),
    ).transition_request(
        request_id=conn.request_id,
        actor="ken",
        lifecycle_status="completed",
        operator_note="removed from broker",
        evidence_reference="proof://broker/removed",
    )

    assert result.request.lifecycle_status == "completed"
    assert result.evidence_created is True
    assert result.event.event_type == "completed"
    assert result.event.event_payload_hash
    assert len(conn.evidence_inserts) == 1
    assert len(conn.event_inserts) == 1
    assert "proof://broker/removed" not in repr(conn.evidence_inserts)


@pytest.mark.asyncio
async def test_transition_removal_request_rejects_terminal_transition() -> None:
    conn = _FakeLifecycleConn(request_status="completed")

    with pytest.raises(
        PrivacyLifecycleTransitionError,
        match="transition invalid",
    ):
        await PrivacyAuthorizationLifecycleRepository(
            conn,  # type: ignore[arg-type]
            _crypto(),
        ).transition_request(
            request_id=conn.request_id,
            actor="ken",
            lifecycle_status="queued",
        )

    assert conn.event_inserts == []


@pytest.mark.asyncio
async def test_prepare_gateway_dry_run_records_gateway_only_proof() -> None:
    conn = _FakeLifecycleConn()
    gateway_calls: list[tuple[str, dict[str, object], int]] = []

    async def fake_gateway_call(
        path: str,
        payload: dict[str, object],
        *,
        timeout_s: int,
    ) -> dict[str, object]:
        gateway_calls.append((path, payload, timeout_s))
        assert payload["outbound_enabled"] is False
        assert payload["would_send"] is False
        assert payload["egress_owner"] == "gateway"
        assert payload["allowed_effects"] == []
        return {
            "status": "dry_run_ready",
            "request_id": payload["request_id"],
            "target_id": payload["target_id"],
            "outbound_enabled": False,
            "would_send": False,
            "idempotency_key_digest": payload["idempotency_key_digest"],
        }

    result = await PrivacyAuthorizationLifecycleRepository(
        conn,  # type: ignore[arg-type]
        _crypto(),
    ).prepare_gateway_dry_run(
        request_id=conn.request_id,
        actor="ken",
        gateway_call=fake_gateway_call,
    )

    assert result.gateway_path == "/v1/cloud/privacy/removal/dry-run"
    assert result.gateway_status == "dry_run_ready"
    assert result.outbound_enabled is False
    assert result.would_send is False
    assert result.event.event_type == "dry_run_prepared"
    assert result.dry_run_payload_hash.startswith("sha256:")
    assert result.idempotency_key_digest.startswith("hmac-sha256:")
    assert conn.dry_run_payload_hash == result.dry_run_payload_hash
    assert len(gateway_calls) == 1
    assert gateway_calls[0][0] == "privacy/removal/dry-run"
    assert "do not leak" not in repr(conn.dry_run_updates)


@pytest.mark.asyncio
async def test_prepare_gateway_dry_run_rejects_terminal_request() -> None:
    conn = _FakeLifecycleConn(request_status="completed")

    async def fake_gateway_call(*args, **kwargs):
        raise AssertionError("terminal requests must not call Gateway")

    with pytest.raises(PrivacyLifecycleTransitionError):
        await PrivacyAuthorizationLifecycleRepository(
            conn,  # type: ignore[arg-type]
            _crypto(),
        ).prepare_gateway_dry_run(
            request_id=conn.request_id,
            actor="ken",
            gateway_call=fake_gateway_call,
        )

    assert conn.dry_run_updates == []
    assert conn.event_inserts == []


@pytest.mark.asyncio
async def test_prepare_gateway_live_preflight_records_kill_switch_proof() -> None:
    conn = _FakeLifecycleConn(dry_run_prepared=True)
    gateway_calls: list[tuple[str, dict[str, object], int]] = []

    async def fake_gateway_call(
        path: str,
        payload: dict[str, object],
        *,
        timeout_s: int,
    ) -> dict[str, object]:
        gateway_calls.append((path, payload, timeout_s))
        assert payload["egress_owner"] == "gateway"
        assert payload["mode"] == "live_preflight"
        assert payload["target_id"] == "beenverified"
        assert "target_url" not in payload
        assert payload["allowed_effects"] == ["target_http_get"]
        assert "broker_form_submit" in payload["blocked_effects"]
        assert payload["approval_binding"]["approval_status"] == "approved"
        return {
            "status": "live_disabled",
            "request_id": payload["request_id"],
            "target_id": payload["target_id"],
            "adapter_kind": payload["adapter_kind"],
            "outbound_enabled": False,
            "would_send": False,
            "target_http_attempted": False,
            "idempotency_key_digest": payload["idempotency_key_digest"],
        }

    result = await PrivacyAuthorizationLifecycleRepository(
        conn,  # type: ignore[arg-type]
        _crypto(),
    ).prepare_gateway_live_preflight(
        request_id=conn.request_id,
        actor="ken",
        gateway_call=fake_gateway_call,
    )

    assert result.gateway_path == "/v1/cloud/privacy/removal/live-preflight"
    assert result.gateway_status == "live_disabled"
    assert result.outbound_enabled is False
    assert result.would_send is False
    assert result.target_http_attempted is False
    assert result.event.event_type == "live_preflight_blocked"
    assert result.live_preflight_payload_hash.startswith("sha256:")
    assert conn.live_preflight_status == "live_disabled"
    assert conn.live_preflight_payload_hash == result.live_preflight_payload_hash
    assert len(gateway_calls) == 1
    assert gateway_calls[0][0] == "privacy/removal/live-preflight"
    assert "https://www.beenverified.com" not in repr(conn.live_preflight_updates)


@pytest.mark.asyncio
async def test_prepare_gateway_live_preflight_requires_fresh_approval() -> None:
    conn = _FakeLifecycleConn(
        dry_run_prepared=True,
        approval_decided_at=datetime.now(UTC) - timedelta(minutes=20),
    )

    async def fake_gateway_call(*args, **kwargs):
        raise AssertionError("stale approvals must not call Gateway")

    with pytest.raises(
        PrivacyLifecycleTransitionError,
        match="fresh approval window expired",
    ):
        await PrivacyAuthorizationLifecycleRepository(
            conn,  # type: ignore[arg-type]
            _crypto(),
        ).prepare_gateway_live_preflight(
            request_id=conn.request_id,
            actor="ken",
            gateway_call=fake_gateway_call,
        )

    assert conn.live_preflight_updates == []


@pytest.mark.asyncio
async def test_prepare_gateway_live_preflight_requires_dry_run_proof() -> None:
    conn = _FakeLifecycleConn(dry_run_prepared=False)

    async def fake_gateway_call(*args, **kwargs):
        raise AssertionError("missing dry-run proof must not call Gateway")

    with pytest.raises(
        PrivacyLifecycleTransitionError,
        match="dry-run proof required",
    ):
        await PrivacyAuthorizationLifecycleRepository(
            conn,  # type: ignore[arg-type]
            _crypto(),
        ).prepare_gateway_live_preflight(
            request_id=conn.request_id,
            actor="ken",
            gateway_call=fake_gateway_call,
        )

    assert conn.live_preflight_updates == []


class _FakeTransaction:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeLifecycleConn:
    def __init__(
        self,
        *,
        subject_id: UUID | None = None,
        active_authorization: bool = True,
        request_status: str = "queued",
        dry_run_prepared: bool = False,
        approval_status: str = "approved",
        action_status: str = "approved",
        approval_decided_at: datetime | None = None,
        approval_expires_at: datetime | None = None,
    ) -> None:
        self.subject_id = subject_id or uuid4()
        self.action_id = uuid4()
        self.approval_queue_id = uuid4()
        self.authorization_id = uuid4()
        self.request_id = uuid4()
        self.event_id = uuid4()
        self.active_authorization = active_authorization
        self.request_status = request_status
        self.approval_status = approval_status
        self.action_status = action_status
        self.approval_decided_at = approval_decided_at or datetime.now(UTC)
        self.approval_expires_at = approval_expires_at or (
            datetime.now(UTC) + timedelta(minutes=30)
        )
        self.evidence_count = 0
        self.authorization_inserts: list[tuple[object, ...]] = []
        self.request_inserts: list[tuple[object, ...]] = []
        self.event_inserts: list[tuple[object, ...]] = []
        self.evidence_inserts: list[tuple[object, ...]] = []
        self.dry_run_updates: list[tuple[object, ...]] = []
        self.live_preflight_updates: list[tuple[object, ...]] = []
        self.dry_run_payload_hash: str | None = (
            "sha256:" + "d" * 64 if dry_run_prepared else None
        )
        self.dry_run_payload_key_version: str | None = (
            "payload-v1" if dry_run_prepared else None
        )
        self.dry_run_prepared_at: datetime | None = (
            datetime.now(UTC) if dry_run_prepared else None
        )
        self.live_preflight_payload_hash: str | None = None
        self.live_preflight_payload_key_version: str | None = None
        self.live_preflight_at: datetime | None = None
        self.live_preflight_status: str | None = None
        self.live_preflight_approval_queue_id: UUID | None = None
        self.gateway_idempotency_key_digest: str | None = None

    def transaction(self):
        return _FakeTransaction()

    async def fetch(self, query: str, *args):
        return []

    async def fetchrow(self, query: str, *args):
        if "FROM public.alpha_privacy_subjects" in query:
            if args[0] != self.subject_id:
                return None
            return _subject_row(self.subject_id)

        if "INSERT INTO public.alpha_privacy_authorizations" in query:
            self.authorization_inserts.append(args)
            return {
                "id": self.authorization_id,
                "subject_id": self.subject_id,
                "authorization_type": args[1],
                "status": "active",
                "authorization_payload_hash": args[4],
                "payload_key_version": args[5],
                "expires_at": args[6],
                "revoked_at": None,
                "created_at": datetime(2026, 6, 18, tzinfo=UTC),
                "updated_at": datetime(2026, 6, 18, tzinfo=UTC),
            }

        if (
            "FROM public.alpha_privacy_removal_requests AS request" in query
            and "WHERE request.action_id = $1" in query
        ):
            return None

        if "JOIN public.alpha_approval_queue AS queue" in query:
            return {
                "approval_queue_id": self.approval_queue_id,
                "approval_tier": "T2",
                "draft_payload_hash": "sha256:" + "1" * 64,
                "action_status": self.action_status,
                "approval_status": self.approval_status,
                "approval_parameters_hash": "f" * 64,
                "decided_at": self.approval_decided_at,
                "expires_at": self.approval_expires_at,
            }

        if "FROM public.alpha_privacy_actions" in query:
            return {
                "id": self.action_id,
                "subject_id": self.subject_id,
                "target_id": "beenverified",
                "draft_payload_hash": "sha256:" + "1" * 64,
                "approval_queue_id": self.approval_queue_id,
                "approval_tier": "T2",
            }

        if "FROM public.alpha_privacy_authorizations" in query:
            if not self.active_authorization:
                return None
            return {"id": self.authorization_id}

        if "INSERT INTO public.alpha_privacy_removal_requests" in query:
            self.request_inserts.append(args)
            self.request_status = "queued"
            return self._request_row(include_target=False)

        if (
            "FROM public.alpha_privacy_removal_requests AS request" in query
            and "WHERE request.id = $1" in query
        ):
            return self._request_row(include_target=True)

        if "UPDATE public.alpha_privacy_removal_requests AS request" in query:
            if "live_preflight_payload_ciphertext" in query:
                self.live_preflight_updates.append(args)
                self.live_preflight_payload_hash = str(args[2])
                self.live_preflight_payload_key_version = str(args[3])
                self.live_preflight_at = args[4]
                self.live_preflight_status = str(args[5])
                self.live_preflight_approval_queue_id = args[6]
                self.gateway_idempotency_key_digest = str(args[7])
                return {"id": self.request_id}
            if "dry_run_payload_ciphertext" in query:
                self.dry_run_updates.append(args)
                self.dry_run_payload_hash = str(args[2])
                self.dry_run_payload_key_version = str(args[3])
                self.dry_run_prepared_at = args[4]
                self.gateway_idempotency_key_digest = str(args[5])
                return {"id": self.request_id}
            self.request_status = str(args[1])
            self.evidence_count += int(args[3])
            return self._request_row(include_target=False)

        if "INSERT INTO public.alpha_privacy_removal_request_events" in query:
            self.event_inserts.append(args)
            return {
                "id": self.event_id,
                "request_id": args[0],
                "event_type": args[1],
                "actor": args[2],
                "event_payload_hash": args[4],
                "created_at": datetime(2026, 6, 18, tzinfo=UTC),
            }

        raise AssertionError(query)

    async def execute(self, query: str, *args):
        if "INSERT INTO public.alpha_privacy_evidence_items" in query:
            self.evidence_inserts.append(args)
            return "INSERT 0 1"
        raise AssertionError(query)

    def _request_row(self, *, include_target: bool) -> dict[str, object]:
        row: dict[str, object] = {
            "id": self.request_id,
            "subject_id": self.subject_id,
            "target_id": "beenverified",
            "authorization_id": self.authorization_id,
            "action_id": self.action_id,
            "lifecycle_status": self.request_status,
            "request_payload_hash": "sha256:" + "2" * 64,
            "payload_key_version": "payload-v1",
            "target_opt_out_method": "web_form",
            "current_evidence_count": self.evidence_count,
            "next_check_at": None,
            "last_event_at": datetime(2026, 6, 18, tzinfo=UTC),
            "dry_run_payload_hash": self.dry_run_payload_hash,
            "dry_run_payload_key_version": self.dry_run_payload_key_version,
            "dry_run_prepared_at": self.dry_run_prepared_at,
            "live_preflight_payload_hash": self.live_preflight_payload_hash,
            "live_preflight_payload_key_version": (
                self.live_preflight_payload_key_version
            ),
            "live_preflight_at": self.live_preflight_at,
            "live_preflight_status": self.live_preflight_status,
            "live_preflight_approval_queue_id": (self.live_preflight_approval_queue_id),
            "gateway_idempotency_key_digest": self.gateway_idempotency_key_digest,
            "created_by_user_id": "ken",
            "created_at": datetime(2026, 6, 18, tzinfo=UTC),
            "updated_at": datetime(2026, 6, 18, tzinfo=UTC),
        }
        if include_target:
            row["target_name"] = "BeenVerified"
            row["target_category"] = "data_broker"
        return row


def _subject_row(subject_id: UUID) -> dict[str, object]:
    return {
        "id": subject_id,
        "user_id": "ken",
        "display_label_digest": "hmac-sha256:" + "1" * 64,
        "role": Role.ADULT.value,
        "guardian_user_id": None,
        "jurisdiction": "US_GA",
        "status": SubjectStatus.ACTIVE.value,
        "subject_payload_hash": "sha256:" + "2" * 64,
        "subject_payload_key_version": "payload-v1",
        "created_at": datetime(2026, 6, 18, tzinfo=UTC),
        "updated_at": datetime(2026, 6, 18, tzinfo=UTC),
    }
