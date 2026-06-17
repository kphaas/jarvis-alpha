from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from brain.services.bluebubbles_client import BlueBubblesClientError
from brain.services.spark_imessage_sender import SparkIMessageSendResult
from brain.services.spark_outbox import (
    SparkOutboxCrypto,
    SparkOutboxCryptoConfig,
)
from brain.services.spark_outbox_send import (
    SparkOutboxSendError,
    resolve_approved_chat_guid_for_outbox,
    send_approved_spark_imessage_outbox,
)
from brain.services.spark_voice_ingest import SparkApprovedSourceRecord


class FakeConn:
    def __init__(self, row: dict[str, object]) -> None:
        self.row = row
        self.fetchvals: list[tuple[str, tuple[object, ...]]] = []
        self.executes: list[tuple[str, tuple[object, ...]]] = []
        self._statuses = ["sending", "sent"]

    async def fetchrow(self, query: str, *args: object):
        assert "get_spark_outbox_item_for_send" in query
        assert args == (UUID("22222222-2222-4222-8222-222222222222"),)
        return self.row

    async def fetchval(self, query: str, *args: object):
        assert "record_spark_outbox_event" in query
        self.fetchvals.append((query, args))
        status = self._statuses.pop(0)
        return json.dumps({"recorded": True, "status": status})

    async def execute(self, query: str, *args: object):
        self.executes.append((query, args))


class FakeSender:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    async def send_text_to_chat(
        self,
        *,
        chat_guid: str,
        text: str,
    ) -> SparkIMessageSendResult:
        self.calls.append({"chat_guid": chat_guid, "text": text})
        return SparkIMessageSendResult(
            status=200,
            message="Success",
            message_ref_hash="message-hash",
        )


class FailingSender:
    async def send_text_to_chat(
        self,
        *,
        chat_guid: str,
        text: str,
    ) -> SparkIMessageSendResult:
        raise BlueBubblesClientError("send failed", status_code=502)


@pytest.mark.asyncio
async def test_send_executor_sends_exact_decrypted_text_and_consumes_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "SPARK_IMESSAGE_APPROVED_CHAT_GUID_KEN_IMESSAGE_APPROVED_20260605_001",
        "approved-chat-guid",
    )
    crypto = _crypto()
    queue_id = UUID("11111111-1111-4111-8111-111111111111")
    outbox_id = UUID("22222222-2222-4222-8222-222222222222")
    target_hash = _sha256_text("approved-chat-guid")
    encrypted = crypto.encrypt_draft_text(
        draft_text="Approved text",
        channel="imessage",
        principal_id="ken",
        target_ref_hash=target_hash,
        approval_queue_id=queue_id,
        approval_parameters_hash="a" * 64,
    )
    conn = FakeConn(
        _row(
            outbox_id=outbox_id,
            queue_id=queue_id,
            target_hash=target_hash,
            ciphertext=encrypted.ciphertext,
            text_hash=encrypted.draft_text_hash,
            key_version=encrypted.payload_key_version,
        )
    )
    sender = FakeSender()

    result = await send_approved_spark_imessage_outbox(
        conn,  # type: ignore[arg-type]
        outbox_id=outbox_id,
        actor_sub="spark-service",
        actor_type="service",
        crypto=crypto,
        sender=sender,
        approved_sources=(_source(),),
    )

    assert result.outbox_status == "sent"
    assert result.approval_status == "executed"
    assert result.message_ref_hash == "message-hash"
    assert sender.calls == [
        {"chat_guid": "approved-chat-guid", "text": "Approved text"}
    ]
    assert len(conn.fetchvals) == 2
    assert conn.fetchvals[0][1][1] == "sending"
    assert conn.fetchvals[1][1][1] == "sent"
    assert conn.executes[-1][0].startswith("SELECT public.consume_approved_queue_item")
    assert conn.executes[-1][1] == (queue_id,)

    event_args = json.dumps(
        [
            str(arg) if isinstance(arg, UUID) else arg
            for _query, args in conn.fetchvals
            for arg in args
            if not isinstance(arg, bytes)
        ]
    ).lower()
    assert "approved text" not in event_args
    assert "approved-chat-guid" not in event_args


@pytest.mark.asyncio
async def test_send_executor_records_send_failed_without_plaintext(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "SPARK_IMESSAGE_APPROVED_CHAT_GUID_KEN_IMESSAGE_APPROVED_20260605_001",
        "approved-chat-guid",
    )
    crypto = _crypto()
    queue_id = UUID("11111111-1111-4111-8111-111111111111")
    outbox_id = UUID("22222222-2222-4222-8222-222222222222")
    target_hash = _sha256_text("approved-chat-guid")
    encrypted = crypto.encrypt_draft_text(
        draft_text="Approved text",
        channel="imessage",
        principal_id="ken",
        target_ref_hash=target_hash,
        approval_queue_id=queue_id,
        approval_parameters_hash="a" * 64,
    )
    conn = FakeConn(
        _row(
            outbox_id=outbox_id,
            queue_id=queue_id,
            target_hash=target_hash,
            ciphertext=encrypted.ciphertext,
            text_hash=encrypted.draft_text_hash,
            key_version=encrypted.payload_key_version,
        )
    )
    conn._statuses = ["sending", "send_failed"]

    with pytest.raises(BlueBubblesClientError):
        await send_approved_spark_imessage_outbox(
            conn,  # type: ignore[arg-type]
            outbox_id=outbox_id,
            actor_sub="spark-service",
            actor_type="service",
            crypto=crypto,
            sender=FailingSender(),
            approved_sources=(_source(),),
        )

    assert len(conn.fetchvals) == 2
    assert conn.fetchvals[0][1][1] == "sending"
    assert conn.fetchvals[1][1][1] == "send_failed"
    assert conn.fetchvals[1][1][5] == "BlueBubblesClientError"
    assert conn.fetchvals[1][1][6] == "spark_imessage_send_failed"
    assert conn.executes == []
    event_args = json.dumps(
        [
            str(arg) if isinstance(arg, UUID) else arg
            for _query, args in conn.fetchvals
            for arg in args
            if not isinstance(arg, bytes)
        ]
    ).lower()
    assert "approved text" not in event_args
    assert "approved-chat-guid" not in event_args


@pytest.mark.asyncio
async def test_send_executor_rejects_unapproved_outbox_before_side_effect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "SPARK_IMESSAGE_APPROVED_CHAT_GUID_KEN_IMESSAGE_APPROVED_20260605_001",
        "approved-chat-guid",
    )
    crypto = _crypto()
    encrypted = crypto.encrypt_draft_text(
        draft_text="Approved text",
        channel="imessage",
        principal_id="ken",
        target_ref_hash=_sha256_text("approved-chat-guid"),
        approval_queue_id=UUID("11111111-1111-4111-8111-111111111111"),
        approval_parameters_hash="a" * 64,
    )
    conn = FakeConn(
        _row(
            outbox_id=UUID("22222222-2222-4222-8222-222222222222"),
            queue_id=UUID("11111111-1111-4111-8111-111111111111"),
            target_hash=_sha256_text("approved-chat-guid"),
            ciphertext=encrypted.ciphertext,
            text_hash=encrypted.draft_text_hash,
            key_version=encrypted.payload_key_version,
            approval_status="pending",
        )
    )
    sender = FakeSender()

    with pytest.raises(SparkOutboxSendError, match="approval_not_ready"):
        await send_approved_spark_imessage_outbox(
            conn,  # type: ignore[arg-type]
            outbox_id=UUID("22222222-2222-4222-8222-222222222222"),
            actor_sub="spark-service",
            actor_type="service",
            crypto=crypto,
            sender=sender,
            approved_sources=(_source(),),
        )

    assert sender.calls == []
    assert conn.fetchvals == []
    assert conn.executes == []


def test_resolve_approved_chat_guid_matches_target_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "SPARK_IMESSAGE_APPROVED_CHAT_GUID_KEN_IMESSAGE_APPROVED_20260605_001",
        "approved-chat-guid",
    )
    item = _item_for_resolve(_sha256_text("approved-chat-guid"))

    assert (
        resolve_approved_chat_guid_for_outbox(
            item,
            approved_sources=(_source(),),
        )
        == "approved-chat-guid"
    )


def _crypto() -> SparkOutboxCrypto:
    return SparkOutboxCrypto(
        SparkOutboxCryptoConfig(
            digest_key="digest-key",
            digest_key_version="digest-v1",
            payload_key="payload-key",
            payload_key_version="payload-v1",
        )
    )


def _source() -> SparkApprovedSourceRecord:
    return SparkApprovedSourceRecord(
        principal_id="ken",
        source="imessage",
        approval_id="ken-imessage-approved-20260605-001",
        source_reference_hash="source-hash",
        source_reference_label="Sweta",
        source_reference_path=None,
        source_sha256=None,
        thread_kind="one_to_one",
        requested_max_messages=20,
        requested_date_window=None,
        relationship_marked=True,
        relationship_approved=True,
        legal_marked=False,
        decision_approved=True,
    )


def _row(
    *,
    outbox_id: UUID,
    queue_id: UUID,
    target_hash: str,
    ciphertext: bytes,
    text_hash: str,
    key_version: str,
    approval_status: str = "approved",
    outbox_status: str = "pending_approval",
) -> dict[str, object]:
    return {
        "outbox_id": outbox_id,
        "channel": "imessage",
        "principal_id": "ken",
        "target_ref_hash": target_hash,
        "target_label": "Sweta",
        "approval_queue_id": queue_id,
        "approval_parameters_hash": "a" * 64,
        "approval_status": approval_status,
        "approval_expires_at": datetime.now(UTC) + timedelta(minutes=10),
        "approval_row_parameters_hash": "a" * 64,
        "draft_text_ciphertext": ciphertext,
        "draft_text_hash": text_hash,
        "payload_key_version": key_version,
        "status": outbox_status,
        "send_attempt_count": 0,
    }


def _item_for_resolve(target_hash: str):
    from brain.services.spark_outbox import SparkOutboxSendItem

    return SparkOutboxSendItem(
        outbox_id=UUID("22222222-2222-4222-8222-222222222222"),
        channel="imessage",
        principal_id="ken",
        target_ref_hash=target_hash,
        target_label="Sweta",
        approval_queue_id=UUID("11111111-1111-4111-8111-111111111111"),
        approval_parameters_hash="a" * 64,
        approval_status="approved",
        approval_expires_at=datetime.now(UTC) + timedelta(minutes=10),
        approval_row_parameters_hash="a" * 64,
        draft_text_ciphertext=b"ciphertext",
        draft_text_hash="hmac-sha256:" + "a" * 64,
        payload_key_version="payload-v1",
        status="pending_approval",
        send_attempt_count=0,
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
