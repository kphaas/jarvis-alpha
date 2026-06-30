"""Approved-send executor for Spark outbox items."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid4

import asyncpg

from brain.services.bluebubbles_client import (
    BlueBubblesClientError,
    BlueBubblesConfigError,
    BlueBubblesPolicyError,
)
from brain.services.spark_imessage_drafts import approved_imessage_chat_guid_for_record
from brain.services.spark_imessage_sender import (
    SparkIMessageSendClient,
    SparkIMessageSendResult,
)
from brain.services.spark_outbox import (
    SparkOutboxCrypto,
    SparkOutboxSendItem,
    consume_spark_outbox_approval,
    decrypt_spark_outbox_draft_text,
    fetch_spark_outbox_item_for_send,
    record_spark_outbox_event,
)
from brain.services.spark_voice_ingest import (
    SparkApprovedSourceRecord,
    load_approved_voice_sources,
)

# ponytail: keep trusted live send as a tiny adult allow-list until contacts are user-managed.
SPARK_TRUSTED_LIVE_TARGETS = frozenset({"sweta", "meagan"})


class SparkOutboxSendError(RuntimeError):
    """Raised when an approved Spark outbox item cannot be sent safely."""


class SparkIMessageSender(Protocol):
    async def send_text_to_chat(
        self,
        *,
        chat_guid: str,
        text: str,
    ) -> SparkIMessageSendResult: ...


@dataclass(frozen=True, slots=True)
class SparkOutboxSendResult:
    outbox_id: str
    outbox_status: str
    approval_queue_id: str
    approval_status: str
    message_ref_hash: str | None
    send_attempt_count: int


@dataclass(frozen=True, slots=True)
class PreparedSparkOutboxSend:
    item: SparkOutboxSendItem
    chat_guid: str
    draft_text: str
    actor_sub: str
    actor_type: str


async def send_approved_spark_imessage_outbox(
    conn: asyncpg.Connection,
    *,
    outbox_id: UUID,
    actor_sub: str,
    actor_type: str,
    crypto: SparkOutboxCrypto,
    sender: SparkIMessageSender | None = None,
    approved_sources: tuple[SparkApprovedSourceRecord, ...] | None = None,
) -> SparkOutboxSendResult:
    prepared = await prepare_approved_spark_imessage_outbox_send(
        conn,
        outbox_id=outbox_id,
        actor_sub=actor_sub,
        actor_type=actor_type,
        crypto=crypto,
        approved_sources=approved_sources,
    )
    try:
        send_result = await execute_prepared_spark_imessage_send(
            prepared,
            sender=sender,
        )
    except Exception as exc:
        await record_prepared_spark_imessage_send_failure(
            conn,
            prepared=prepared,
            exc=exc,
        )
        if isinstance(
            exc,
            (BlueBubblesClientError, BlueBubblesConfigError, BlueBubblesPolicyError),
        ):
            raise
        raise SparkOutboxSendError("spark_imessage_send_failed") from exc

    return await record_prepared_spark_imessage_send_success(
        conn,
        prepared=prepared,
        send_result=send_result,
    )


async def prepare_approved_spark_imessage_outbox_send(
    conn: asyncpg.Connection,
    *,
    outbox_id: UUID,
    actor_sub: str,
    actor_type: str,
    crypto: SparkOutboxCrypto,
    approved_sources: tuple[SparkApprovedSourceRecord, ...] | None = None,
) -> PreparedSparkOutboxSend:
    item = await fetch_spark_outbox_item_for_send(conn, outbox_id=outbox_id)
    if item is None:
        raise SparkOutboxSendError("spark_outbox_not_found")
    _validate_sendable(item)

    draft_text = decrypt_spark_outbox_draft_text(item, crypto=crypto)
    chat_guid = resolve_approved_chat_guid_for_outbox(
        item,
        approved_sources=approved_sources,
    )

    await record_spark_outbox_event(
        conn,
        outbox_id=item.outbox_id,
        event_type="sending",
        actor_sub=actor_sub,
        actor_type=actor_type,
        metadata={
            "approval_queue_id": str(item.approval_queue_id),
            "draft_text_hash": item.draft_text_hash,
        },
    )
    return PreparedSparkOutboxSend(
        item=item,
        chat_guid=chat_guid,
        draft_text=draft_text,
        actor_sub=actor_sub,
        actor_type=actor_type,
    )


async def prepare_trusted_live_spark_imessage_outbox_send(
    conn: asyncpg.Connection,
    *,
    outbox_id: UUID,
    actor_sub: str,
    actor_type: str,
    crypto: SparkOutboxCrypto,
    approved_sources: tuple[SparkApprovedSourceRecord, ...] | None = None,
) -> PreparedSparkOutboxSend:
    item = await fetch_spark_outbox_item_for_send(conn, outbox_id=outbox_id)
    if item is None:
        raise SparkOutboxSendError("spark_outbox_not_found")
    _validate_trusted_live_sendable(item)

    if item.approval_status == "pending":
        await _approve_trusted_live_outbox_queue(
            conn,
            item=item,
            actor_sub=actor_sub,
        )

    return await prepare_approved_spark_imessage_outbox_send(
        conn,
        outbox_id=outbox_id,
        actor_sub=actor_sub,
        actor_type=actor_type,
        crypto=crypto,
        approved_sources=approved_sources,
    )


async def execute_prepared_spark_imessage_send(
    prepared: PreparedSparkOutboxSend,
    *,
    sender: SparkIMessageSender | None = None,
) -> SparkIMessageSendResult:
    active_sender = sender or SparkIMessageSendClient()
    return await active_sender.send_text_to_chat(
        chat_guid=prepared.chat_guid,
        text=prepared.draft_text,
    )


async def record_prepared_spark_imessage_send_failure(
    conn: asyncpg.Connection,
    *,
    prepared: PreparedSparkOutboxSend,
    exc: Exception,
) -> None:
    await record_spark_outbox_event(
        conn,
        outbox_id=prepared.item.outbox_id,
        event_type="send_failed",
        actor_sub=prepared.actor_sub,
        actor_type=prepared.actor_type,
        metadata={"approval_queue_id": str(prepared.item.approval_queue_id)},
        error_class=exc.__class__.__name__,
        error_message="spark_imessage_send_failed",
    )


async def record_prepared_spark_imessage_send_success(
    conn: asyncpg.Connection,
    *,
    prepared: PreparedSparkOutboxSend,
    send_result: SparkIMessageSendResult,
) -> SparkOutboxSendResult:
    status = await record_spark_outbox_event(
        conn,
        outbox_id=prepared.item.outbox_id,
        event_type="sent",
        actor_sub=prepared.actor_sub,
        actor_type=prepared.actor_type,
        metadata={
            "approval_queue_id": str(prepared.item.approval_queue_id),
            "bluebubbles_status": send_result.status,
            "message_ref_hash": send_result.message_ref_hash or "",
        },
    )
    await consume_spark_outbox_approval(
        conn,
        approval_queue_id=prepared.item.approval_queue_id,
    )
    return SparkOutboxSendResult(
        outbox_id=str(prepared.item.outbox_id),
        outbox_status=status,
        approval_queue_id=str(prepared.item.approval_queue_id),
        approval_status="executed",
        message_ref_hash=send_result.message_ref_hash,
        send_attempt_count=prepared.item.send_attempt_count + 1,
    )


def resolve_approved_chat_guid_for_outbox(
    item: SparkOutboxSendItem,
    *,
    approved_sources: tuple[SparkApprovedSourceRecord, ...] | None = None,
) -> str:
    sources = approved_sources or load_approved_voice_sources(
        principal_id=item.principal_id
    )
    for record in sources:
        if record.source != "imessage" or not record.decision_approved:
            continue
        try:
            chat_guid = approved_imessage_chat_guid_for_record(record)
        except Exception:
            continue
        if _sha256_text(chat_guid) == item.target_ref_hash:
            return chat_guid
    raise SparkOutboxSendError("spark_outbox_target_not_configured")


def _validate_sendable(item: SparkOutboxSendItem) -> None:
    if item.channel != "imessage":
        raise SparkOutboxSendError("spark_outbox_channel_not_imessage")
    if item.status in {"sent", "cancelled"}:
        raise SparkOutboxSendError("spark_outbox_already_final")
    if item.status == "sending":
        raise SparkOutboxSendError("spark_outbox_send_in_progress")
    if item.approval_status != "approved":
        raise SparkOutboxSendError("spark_outbox_approval_not_ready")
    if item.approval_parameters_hash != item.approval_row_parameters_hash:
        raise SparkOutboxSendError("spark_outbox_approval_hash_mismatch")


def is_trusted_live_spark_target(value: str | None) -> bool:
    target = (value or "").strip().lower()
    return bool(target and target in SPARK_TRUSTED_LIVE_TARGETS)


def _validate_trusted_live_sendable(item: SparkOutboxSendItem) -> None:
    if item.channel != "imessage":
        raise SparkOutboxSendError("spark_outbox_channel_not_imessage")
    if item.status in {"sent", "cancelled"}:
        raise SparkOutboxSendError("spark_outbox_already_final")
    if item.status == "sending":
        raise SparkOutboxSendError("spark_outbox_send_in_progress")
    if item.approval_parameters_hash != item.approval_row_parameters_hash:
        raise SparkOutboxSendError("spark_outbox_approval_hash_mismatch")
    if item.approval_status not in {"pending", "approved"}:
        raise SparkOutboxSendError("spark_outbox_approval_not_ready")
    if not is_trusted_live_spark_target(item.target_label):
        raise SparkOutboxSendError("spark_outbox_trusted_live_target_not_allowed")


async def _approve_trusted_live_outbox_queue(
    conn: asyncpg.Connection,
    *,
    item: SparkOutboxSendItem,
    actor_sub: str,
) -> None:
    try:
        rows = await conn.fetch(
            "SELECT * FROM public.decide_approval($1::uuid, $2, $3, $4)",
            item.approval_queue_id,
            "approved",
            actor_sub,
            uuid4().hex,
        )
    except Exception as exc:
        if "APPROVAL_ALREADY_DECIDED" in str(exc):
            return
        raise
    if not rows:
        raise SparkOutboxSendError("spark_outbox_trusted_live_approval_failed")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
