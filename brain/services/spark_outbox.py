"""Encrypted Spark outbox storage for approved draft handoff."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping
from uuid import UUID

import asyncpg
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from brain.config.secrets import get_secret
from brain.services.spark_draft_approvals import spark_draft_parameters_hash
from brain.services.spark_imessage_drafts import SparkDraftProposal

SPARK_OUTBOX_DIGEST_KEY = "SPARK_OUTBOX_DIGEST_KEY"
SPARK_OUTBOX_DIGEST_KEY_VERSION = "SPARK_OUTBOX_DIGEST_KEY_VERSION"
SPARK_OUTBOX_PAYLOAD_KEY = "SPARK_OUTBOX_PAYLOAD_KEY"
SPARK_OUTBOX_PAYLOAD_KEY_VERSION = "SPARK_OUTBOX_PAYLOAD_KEY_VERSION"

_ENVELOPE_PREFIX = b"spark-outbox-aesgcm:v1:"
_NONCE_BYTES = 12


class SparkOutboxConfigError(RuntimeError):
    """Raised when Spark outbox crypto cannot be configured safely."""


class SparkOutboxStoreError(RuntimeError):
    """Raised when Spark outbox storage returns an invalid result."""


@dataclass(frozen=True, slots=True)
class SparkOutboxCryptoConfig:
    digest_key: str
    digest_key_version: str
    payload_key: str
    payload_key_version: str


@dataclass(frozen=True, slots=True)
class SparkOutboxEncryptedDraft:
    ciphertext: bytes
    draft_text_hash: str
    payload_hash: str
    payload_key_version: str


@dataclass(frozen=True, slots=True)
class SparkOutboxCreateResult:
    outbox_id: str | None
    status: str
    draft_text_hash: str
    created: bool
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class SparkOutboxSendItem:
    outbox_id: UUID
    channel: str
    principal_id: str
    target_ref_hash: str
    target_label: str
    approval_queue_id: UUID
    approval_parameters_hash: str
    approval_status: str
    approval_expires_at: datetime | None
    approval_row_parameters_hash: str
    draft_text_ciphertext: bytes
    draft_text_hash: str
    payload_key_version: str
    status: str
    send_attempt_count: int


class SparkOutboxCrypto:
    """App-side encryption and keyed digests for Spark draft outbox records."""

    def __init__(self, config: SparkOutboxCryptoConfig) -> None:
        self._digest_key = _require_non_empty(config.digest_key, "digest_key")
        self.digest_key_version = _require_non_empty(
            config.digest_key_version,
            "digest_key_version",
        )
        self._payload_key = _derive_aes_key(
            _require_non_empty(config.payload_key, "payload_key")
        )
        self.payload_key_version = _require_non_empty(
            config.payload_key_version,
            "payload_key_version",
        )

    def digest_value(self, namespace: str, value: str) -> str:
        canonical = _canonical_json(
            {
                "namespace": _require_non_empty(namespace, "namespace"),
                "value": _require_non_empty(value, "value"),
            }
        )
        digest = hmac.new(
            self._digest_key.encode("utf-8"),
            canonical,
            hashlib.sha256,
        ).hexdigest()
        return f"hmac-sha256:{digest}"

    def encrypt_draft_text(
        self,
        *,
        draft_text: str,
        channel: str,
        principal_id: str,
        target_ref_hash: str,
        approval_queue_id: UUID,
        approval_parameters_hash: str,
    ) -> SparkOutboxEncryptedDraft:
        text = _require_non_empty(draft_text, "draft_text")
        payload = {
            "approval_parameters_hash": approval_parameters_hash,
            "approval_queue_id": str(approval_queue_id),
            "channel": channel,
            "draft_text": text,
            "principal_id": principal_id,
            "target_ref_hash": target_ref_hash,
        }
        plaintext = _canonical_json(payload)
        nonce = os.urandom(_NONCE_BYTES)
        aad = self.payload_key_version.encode("utf-8")
        ciphertext = AESGCM(self._payload_key).encrypt(nonce, plaintext, aad)
        envelope = _ENVELOPE_PREFIX + base64.urlsafe_b64encode(nonce + ciphertext)
        return SparkOutboxEncryptedDraft(
            ciphertext=envelope,
            draft_text_hash=self.digest_value("spark_outbox_draft_text", text),
            payload_hash=sha256_digest(envelope),
            payload_key_version=self.payload_key_version,
        )

    def decrypt_draft_text(self, draft: SparkOutboxEncryptedDraft) -> str:
        if not draft.ciphertext.startswith(_ENVELOPE_PREFIX):
            raise ValueError("unsupported spark outbox payload envelope")
        encoded = draft.ciphertext.removeprefix(_ENVELOPE_PREFIX)
        raw = base64.urlsafe_b64decode(encoded)
        nonce = raw[:_NONCE_BYTES]
        ciphertext = raw[_NONCE_BYTES:]
        aad = draft.payload_key_version.encode("utf-8")
        plaintext = AESGCM(self._payload_key).decrypt(nonce, ciphertext, aad)
        decoded = json.loads(plaintext.decode("utf-8"))
        if not isinstance(decoded, dict):
            raise ValueError("spark outbox payload must decrypt to an object")
        draft_text = decoded.get("draft_text")
        if not isinstance(draft_text, str) or not draft_text.strip():
            raise ValueError("spark outbox payload missing draft text")
        return draft_text


def load_spark_outbox_crypto() -> SparkOutboxCrypto:
    values = {
        SPARK_OUTBOX_DIGEST_KEY: _secret(SPARK_OUTBOX_DIGEST_KEY),
        SPARK_OUTBOX_DIGEST_KEY_VERSION: _secret(SPARK_OUTBOX_DIGEST_KEY_VERSION),
        SPARK_OUTBOX_PAYLOAD_KEY: _secret(SPARK_OUTBOX_PAYLOAD_KEY),
        SPARK_OUTBOX_PAYLOAD_KEY_VERSION: _secret(SPARK_OUTBOX_PAYLOAD_KEY_VERSION),
    }
    missing = [name for name, value in values.items() if not value.strip()]
    if missing:
        raise SparkOutboxConfigError("spark_outbox_config_missing")

    try:
        return SparkOutboxCrypto(
            SparkOutboxCryptoConfig(
                digest_key=values[SPARK_OUTBOX_DIGEST_KEY],
                digest_key_version=values[SPARK_OUTBOX_DIGEST_KEY_VERSION],
                payload_key=values[SPARK_OUTBOX_PAYLOAD_KEY],
                payload_key_version=values[SPARK_OUTBOX_PAYLOAD_KEY_VERSION],
            )
        )
    except ValueError as exc:
        raise SparkOutboxConfigError("spark_outbox_config_invalid") from exc


async def create_spark_outbox_item(
    conn: asyncpg.Connection,
    *,
    proposal: SparkDraftProposal,
    approval_queue_id: UUID,
    actor_sub: str,
    actor_type: str,
    crypto: SparkOutboxCrypto,
) -> SparkOutboxCreateResult:
    channel = "imessage"
    target_ref_hash = proposal.context.chat_guid_hash
    approval_parameters_hash = spark_draft_parameters_hash(proposal)
    encrypted = crypto.encrypt_draft_text(
        draft_text=proposal.draft_text,
        channel=channel,
        principal_id=proposal.principal_id,
        target_ref_hash=target_ref_hash,
        approval_queue_id=approval_queue_id,
        approval_parameters_hash=approval_parameters_hash,
    )
    event_metadata = _safe_event_metadata(proposal, encrypted.payload_hash)
    raw_result = await conn.fetchval(
        """
        SELECT public.create_spark_outbox_item(
            $1, $2, $3, $4, $5::uuid, $6, $7::bytea, $8, $9, $10, $11, $12::jsonb
        )
        """,
        channel,
        proposal.principal_id,
        target_ref_hash,
        _target_label(proposal),
        approval_queue_id,
        approval_parameters_hash,
        encrypted.ciphertext,
        encrypted.draft_text_hash,
        encrypted.payload_key_version,
        actor_sub,
        actor_type,
        json.dumps(event_metadata, sort_keys=True, separators=(",", ":")),
    )
    result = _decode_json_result(raw_result)
    return SparkOutboxCreateResult(
        outbox_id=_string_or_none(result.get("outbox_id")),
        status=str(result.get("status") or "unknown"),
        draft_text_hash=encrypted.draft_text_hash,
        created=bool(result.get("created")),
        reason=_string_or_none(result.get("reason")),
    )


async def fetch_spark_outbox_item_for_send(
    conn: asyncpg.Connection,
    *,
    outbox_id: UUID,
) -> SparkOutboxSendItem | None:
    row = await conn.fetchrow(
        """
        SELECT *
        FROM public.get_spark_outbox_item_for_send($1::uuid)
        """,
        outbox_id,
    )
    if row is None:
        return None
    return SparkOutboxSendItem(
        outbox_id=UUID(str(row["outbox_id"])),
        channel=str(row["channel"]),
        principal_id=str(row["principal_id"]),
        target_ref_hash=str(row["target_ref_hash"]),
        target_label=str(row["target_label"]),
        approval_queue_id=UUID(str(row["approval_queue_id"])),
        approval_parameters_hash=str(row["approval_parameters_hash"]),
        approval_status=str(row["approval_status"]),
        approval_expires_at=row["approval_expires_at"],
        approval_row_parameters_hash=str(row["approval_row_parameters_hash"]),
        draft_text_ciphertext=bytes(row["draft_text_ciphertext"]),
        draft_text_hash=str(row["draft_text_hash"]),
        payload_key_version=str(row["payload_key_version"]),
        status=str(row["status"]),
        send_attempt_count=int(row["send_attempt_count"]),
    )


def decrypt_spark_outbox_draft_text(
    item: SparkOutboxSendItem,
    *,
    crypto: SparkOutboxCrypto,
) -> str:
    encrypted = SparkOutboxEncryptedDraft(
        ciphertext=item.draft_text_ciphertext,
        draft_text_hash=item.draft_text_hash,
        payload_hash="sha256:" + "0" * 64,
        payload_key_version=item.payload_key_version,
    )
    draft_text = crypto.decrypt_draft_text(encrypted)
    expected_hash = crypto.digest_value("spark_outbox_draft_text", draft_text)
    if not hmac.compare_digest(expected_hash, item.draft_text_hash):
        raise SparkOutboxStoreError("spark_outbox_draft_text_hash_mismatch")
    return draft_text


async def record_spark_outbox_event(
    conn: asyncpg.Connection,
    *,
    outbox_id: UUID,
    event_type: str,
    actor_sub: str,
    actor_type: str,
    metadata: Mapping[str, object] | None = None,
    error_class: str | None = None,
    error_message: str | None = None,
) -> str:
    result = await conn.fetchval(
        """
        SELECT public.record_spark_outbox_event(
            $1::uuid, $2, $3, $4, $5::jsonb, $6, $7
        )
        """,
        outbox_id,
        event_type,
        actor_sub,
        actor_type,
        json.dumps(metadata or {}, sort_keys=True, separators=(",", ":")),
        error_class,
        error_message,
    )
    decoded = _decode_json_result(result)
    status = _string_or_none(decoded.get("status"))
    if status is None:
        raise SparkOutboxStoreError("spark_outbox_event_result_invalid")
    return status


async def consume_spark_outbox_approval(
    conn: asyncpg.Connection,
    *,
    approval_queue_id: UUID,
) -> None:
    await conn.execute(
        "SELECT public.consume_approved_queue_item($1::uuid)",
        approval_queue_id,
    )


def sha256_digest(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _safe_event_metadata(
    proposal: SparkDraftProposal,
    payload_hash: str,
) -> dict[str, object]:
    return {
        "approval_ref_hash": proposal.context.approval_ref_hash,
        "blocked_sensitivity": list(proposal.blocked_sensitivity),
        "context_messages_read": len(proposal.context.messages),
        "detected_sensitivity": list(proposal.detected_sensitivity),
        "draft_engine": proposal.draft_engine,
        "draft_quality_score": proposal.draft_quality.score,
        "draft_version": proposal.draft_version,
        "payload_hash": payload_hash,
        "principal_sent_messages": proposal.context.principal_sent_messages,
        "runtime_context_messages": proposal.context.runtime_context_messages,
        "source_reference_hash": proposal.context.source_reference_hash,
    }


def _target_label(proposal: SparkDraftProposal) -> str:
    label = proposal.conversation_summary.reply_target_label.strip()
    return label or "Approved iMessage thread"


def _decode_json_result(raw_result: object) -> Mapping[str, object]:
    if isinstance(raw_result, str):
        decoded = json.loads(raw_result)
    elif isinstance(raw_result, Mapping):
        decoded = raw_result
    else:
        raise SparkOutboxStoreError("spark_outbox_result_invalid")
    if not isinstance(decoded, Mapping):
        raise SparkOutboxStoreError("spark_outbox_result_invalid")
    return decoded


def _string_or_none(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def _secret(name: str) -> str:
    value = os.getenv(name)
    if value is not None:
        return value
    try:
        return get_secret(name)
    except KeyError:
        return ""


def _canonical_json(payload: Mapping[str, object]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _derive_aes_key(payload_key: str) -> bytes:
    return hashlib.sha256(payload_key.encode("utf-8")).digest()


def _require_non_empty(value: str, field_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{field_name} is required")
    return value
