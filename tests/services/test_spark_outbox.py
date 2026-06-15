from __future__ import annotations

import json
from uuid import UUID

import pytest

from brain.services.spark_draft_approvals import spark_draft_parameters_hash
from brain.services.spark_imessage_drafts import (
    SparkDraftContext,
    SparkDraftConversationSummary,
    SparkDraftProposal,
    SparkDraftQualityCheck,
    SparkDraftQualityScorecard,
    SparkDraftSourceReadiness,
    SparkRuntimeMessage,
)
from brain.services.spark_outbox import (
    SparkOutboxCrypto,
    SparkOutboxCryptoConfig,
    SparkOutboxEncryptedDraft,
    create_spark_outbox_item,
)


class FakeConn:
    def __init__(self) -> None:
        self.query = ""
        self.args: tuple[object, ...] = ()

    async def fetchval(self, query: str, *args: object) -> str:
        self.query = query
        self.args = args
        return json.dumps(
            {
                "created": True,
                "outbox_id": "22222222-2222-4222-8222-222222222222",
                "status": "pending_approval",
            }
        )


def test_spark_outbox_crypto_encrypts_exact_text_without_plaintext() -> None:
    crypto = _crypto()

    encrypted = crypto.encrypt_draft_text(
        draft_text="Edited draft for review.",
        channel="imessage",
        principal_id="ken",
        target_ref_hash="chat-hash",
        approval_queue_id=UUID("11111111-1111-4111-8111-111111111111"),
        approval_parameters_hash="a" * 64,
    )

    assert encrypted.ciphertext.startswith(b"spark-outbox-aesgcm:v1:")
    assert b"Edited draft for review" not in encrypted.ciphertext
    assert encrypted.draft_text_hash.startswith("hmac-sha256:")
    assert encrypted.payload_hash.startswith("sha256:")
    assert encrypted.payload_key_version == "payload-v1"
    assert crypto.decrypt_draft_text(encrypted) == "Edited draft for review."


def test_spark_outbox_text_digest_is_keyed() -> None:
    crypto = _crypto()
    other_crypto = SparkOutboxCrypto(
        SparkOutboxCryptoConfig(
            digest_key="other-digest-key",
            digest_key_version="digest-v1",
            payload_key="payload-key",
            payload_key_version="payload-v1",
        )
    )

    assert crypto.digest_value("draft", "Short reply") == crypto.digest_value(
        "draft",
        "Short reply",
    )
    assert crypto.digest_value("draft", "Short reply") != other_crypto.digest_value(
        "draft",
        "Short reply",
    )


@pytest.mark.asyncio
async def test_create_spark_outbox_item_stores_ciphertext_and_safe_metadata() -> None:
    proposal = _proposal()
    conn = FakeConn()
    queue_id = UUID("11111111-1111-4111-8111-111111111111")

    result = await create_spark_outbox_item(
        conn,  # type: ignore[arg-type]
        proposal=proposal,
        approval_queue_id=queue_id,
        actor_sub="spark-service",
        actor_type="service",
        crypto=_crypto(),
    )

    assert result.outbox_id == "22222222-2222-4222-8222-222222222222"
    assert result.status == "pending_approval"
    assert result.created is True
    assert result.draft_text_hash.startswith("hmac-sha256:")
    assert "create_spark_outbox_item" in conn.query
    assert conn.args[0] == "imessage"
    assert conn.args[1] == "ken"
    assert conn.args[2] == "chat-hash"
    assert conn.args[3] == "Sweta"
    assert conn.args[4] == queue_id
    assert conn.args[5] == spark_draft_parameters_hash(proposal)
    assert isinstance(conn.args[6], bytes)
    assert b"Tell her I am on it" not in conn.args[6]
    assert conn.args[7] == result.draft_text_hash
    assert conn.args[8] == "payload-v1"
    assert conn.args[9] == "spark-service"
    assert conn.args[10] == "service"

    serializable_args = [
        str(arg) if isinstance(arg, UUID) else arg
        for arg in conn.args
        if not isinstance(arg, bytes)
    ]
    serialized = json.dumps(serializable_args).lower()
    assert "tell her i am on it" not in serialized
    assert "private inbound body" not in serialized
    assert "ken sent private body" not in serialized
    assert "approved-chat-guid" not in serialized

    metadata = json.loads(str(conn.args[11]))
    assert metadata["draft_version"] == "spark-imessage-draft/v0.2"
    assert metadata["context_messages_read"] == 2
    assert metadata["payload_hash"].startswith("sha256:")
    assert "draft_text" not in metadata


def test_spark_outbox_decrypt_rejects_wrong_envelope() -> None:
    crypto = _crypto()

    with pytest.raises(ValueError, match="unsupported spark outbox payload envelope"):
        crypto.decrypt_draft_text(
            SparkOutboxEncryptedDraft(
                ciphertext=b"wrong:v1:payload",
                draft_text_hash="hmac-sha256:" + "a" * 64,
                payload_hash="sha256:" + "b" * 64,
                payload_key_version="payload-v1",
            )
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


def _proposal() -> SparkDraftProposal:
    return SparkDraftProposal(
        principal_id="ken",
        draft_text="Tell her I am on it.",
        context=SparkDraftContext(
            principal_id="ken",
            approval_ref_hash="approval-hash",
            source_reference_hash="source-hash",
            chat_guid_hash="chat-hash",
            messages=(
                SparkRuntimeMessage(
                    message_ref_hash="msg-1",
                    is_from_me=False,
                    body_text="private inbound body",
                ),
                SparkRuntimeMessage(
                    message_ref_hash="msg-2",
                    is_from_me=True,
                    body_text="ken sent private body",
                ),
            ),
        ),
        conversation_summary=SparkDraftConversationSummary(
            channel="iMessage",
            voice_principal_label="Ken",
            reply_target_label="Sweta",
            reply_target_confidence="approved_source_label",
        ),
        draft_quality=SparkDraftQualityScorecard(
            score=100,
            verdict="strong",
            checks=(
                SparkDraftQualityCheck(
                    key="length",
                    label="Short enough",
                    passed=True,
                    detail="5 words; Spark should stay short to medium.",
                ),
            ),
        ),
        source_readiness=(
            SparkDraftSourceReadiness(
                source="imessage",
                channel="Text",
                status="live_runtime_context",
                detail="Approved iMessage thread is feeding this draft at runtime.",
            ),
        ),
        warnings=("draft_only_no_send",),
    )
