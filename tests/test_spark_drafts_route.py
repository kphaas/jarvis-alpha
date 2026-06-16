from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException

from brain.middleware.approval_classes import classify_route, determine_risk_tier
from brain.routes import spark_drafts
from brain.services.spark_imessage_drafts import (
    SparkDraftContext,
    SparkDraftConversationSummary,
    SparkDraftQualityCheck,
    SparkDraftQualityScorecard,
    SparkDraftContextError,
    SparkDraftProposal,
    SparkDraftSourceReadiness,
    SparkRuntimeMessage,
)
from brain.services.spark_outbox import SparkOutboxListItem
from brain.services.spark_voice_feedback import SparkDraftEditFeedbackResult
from brain.services.spark_voice_ingest import SparkApprovedSourceRecord


def _request(scopes: list[str] | None = None):
    return SimpleNamespace(
        state=SimpleNamespace(
            actor_type="service",
            role=None,
            user_id="spark-service",
            scopes=scopes or ["spark.draft", "imessage.read"],
            iss="spark",
        )
    )


class _FakeLogger:
    def __init__(self) -> None:
        self.infos: list[tuple[str, dict[str, object]]] = []
        self.warnings: list[tuple[str, dict[str, object]]] = []
        self.errors: list[tuple[str, dict[str, object]]] = []

    def info(self, message: str, *, extra: dict[str, object]) -> None:
        self.infos.append((message, extra))

    def warning(self, message: str, *, extra: dict[str, object]) -> None:
        self.warnings.append((message, extra))

    def error(self, message: str, *, extra: dict[str, object]) -> None:
        self.errors.append((message, extra))


def _stub_personality_memory(
    monkeypatch: pytest.MonkeyPatch,
    rows: list[dict[str, object]] | None = None,
) -> object:
    fake_conn = object()

    async def fake_fetch(conn: object, principal_id: str):
        assert conn is fake_conn
        assert principal_id == "ken"
        return rows or []

    monkeypatch.setattr(
        spark_drafts,
        "rls_connection",
        lambda request: _AsyncContext(fake_conn),
    )
    monkeypatch.setattr(spark_drafts, "fetch_personality_memory", fake_fetch)
    return fake_conn


def test_spark_imessage_draft_route_is_classified_t2_write() -> None:
    target_classes = classify_route("GET", "/v1/spark/drafts/imessage/targets")
    preview_classes = classify_route("GET", "/v1/spark/drafts/imessage/target-preview")
    outbox_classes = classify_route("GET", "/v1/spark/drafts/imessage/outbox")
    assert target_classes == ["read", "security_read"]
    assert determine_risk_tier(target_classes) == "T2"
    assert preview_classes == ["read", "security_read"]
    assert determine_risk_tier(preview_classes) == "T2"
    assert outbox_classes == ["read", "security_read"]
    assert determine_risk_tier(outbox_classes) == "T2"

    classes = classify_route("POST", "/v1/spark/drafts/imessage")

    assert classes == ["write", "security_write"]
    assert determine_risk_tier(classes) == "T2"

    approval_classes = classify_route(
        "POST", "/v1/spark/drafts/imessage/approval-request"
    )
    feedback_classes = classify_route("POST", "/v1/spark/drafts/imessage/feedback")
    send_classes = classify_route(
        "POST",
        "/v1/spark/drafts/imessage/outbox/22222222-2222-4222-8222-222222222222/send",
    )
    assert approval_classes == ["write", "security_write"]
    assert determine_risk_tier(approval_classes) == "T2"
    assert send_classes == [
        "write",
        "security_write",
        "external_call",
        "imessage_send",
    ]
    assert determine_risk_tier(send_classes) == "T4"
    assert feedback_classes == ["write", "security_write"]
    assert determine_risk_tier(feedback_classes) == "T2"


@pytest.mark.asyncio
async def test_spark_imessage_draft_requires_both_scopes() -> None:
    payload = spark_drafts.SparkIMessageDraftRequest(
        reply_goal="Tell her I am on it",
    )

    for scopes in (["spark.draft"], ["imessage.read"]):
        with pytest.raises(HTTPException) as exc_info:
            await spark_drafts.spark_imessage_draft(_request(scopes), payload, "user")

        assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_spark_imessage_draft_approval_requires_both_scopes() -> None:
    payload = spark_drafts.SparkIMessageDraftApprovalRequest(
        reply_goal="Tell her I am on it",
    )

    for scopes in (["spark.draft"], ["imessage.read"]):
        with pytest.raises(HTTPException) as exc_info:
            await spark_drafts.spark_imessage_draft_approval_request(
                _request(scopes), payload, "user"
            )

        assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_spark_imessage_send_approved_outbox_requires_send_scope() -> None:
    outbox_id = UUID("22222222-2222-4222-8222-222222222222")

    for scopes in (["spark.draft"], ["imessage.send"]):
        with pytest.raises(HTTPException) as exc_info:
            await spark_drafts.spark_imessage_send_approved_outbox(
                _request(scopes),
                outbox_id,
                "user",
            )

        assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_spark_imessage_draft_targets_list_approved_threads_safely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_logger = _FakeLogger()
    monkeypatch.setattr(spark_drafts, "logger", fake_logger)
    monkeypatch.setattr(
        spark_drafts,
        "load_approved_voice_sources",
        lambda principal_id: (
            SparkApprovedSourceRecord(
                principal_id=principal_id,
                source="imessage",
                approval_id="ken-imessage-approved-20260605-001",
                source_reference_hash="source-hash",
                source_reference_label="Sweta",
                source_reference_path=None,
                source_sha256=None,
                thread_kind="one_to_one",
                requested_max_messages=200,
                requested_date_window=None,
                relationship_marked=True,
                relationship_approved=True,
                legal_marked=False,
                decision_approved=True,
            ),
            SparkApprovedSourceRecord(
                principal_id=principal_id,
                source="gmail",
                approval_id="ken-gmail-approved",
                source_reference_hash="gmail-hash",
                source_reference_label=None,
                source_reference_path=None,
                source_sha256=None,
                thread_kind="one_to_one",
                requested_max_messages=250,
                requested_date_window="180d",
                relationship_marked=False,
                relationship_approved=False,
                legal_marked=False,
                decision_approved=True,
            ),
            SparkApprovedSourceRecord(
                principal_id=principal_id,
                source="imessage",
                approval_id="ken-imessage-approved-20260605-002",
                source_reference_hash="mother-hash",
                source_reference_label="Mother",
                source_reference_path=None,
                source_sha256=None,
                thread_kind="one_to_one",
                requested_max_messages=200,
                requested_date_window=None,
                relationship_marked=True,
                relationship_approved=True,
                legal_marked=False,
                decision_approved=True,
            ),
        ),
    )

    response = await spark_drafts.spark_imessage_draft_targets(
        _request(),
        "ken",
        "user",
    )

    payload = response.model_dump()
    assert payload == {
        "principal_id": "ken",
        "targets": [
            {
                "approval_id": "ken-imessage-approved-20260605-001",
                "label": "Sweta",
                "channel": "iMessage",
                "thread_kind": "one_to_one",
                "relationship_marked": True,
                "relationship_approved": True,
                "legal_marked": False,
            }
        ],
    }
    logs = json.dumps(fake_logger.infos).lower()
    assert "private inbound body" not in logs
    assert "approved-chat-guid" not in logs
    assert "sweta" not in logs
    assert "target_count" in logs


@pytest.mark.asyncio
async def test_spark_imessage_target_preview_returns_last_eight_safely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_logger = _FakeLogger()
    personality_rows = [
        {
            "kind": "relationship",
            "content": "Sweta: partner; default hybrid_review; approval required True.",
        }
    ]
    monkeypatch.setattr(spark_drafts, "logger", fake_logger)
    _stub_personality_memory(monkeypatch, personality_rows)

    async def fake_preview(**kwargs):
        assert kwargs == {
            "principal_id": "ken",
            "approval_id": "ken-imessage-approved-20260605-001",
            "max_context_messages": 8,
            "personality_memory_rows": personality_rows,
        }
        proposal = _proposal()
        return spark_drafts.SparkIMessageTargetPreview(
            record=SparkApprovedSourceRecord(
                principal_id="ken",
                source="imessage",
                approval_id="ken-imessage-approved-20260605-001",
                source_reference_hash="source-hash",
                source_reference_label="Sweta",
                source_reference_path=None,
                source_sha256=None,
                thread_kind="one_to_one",
                requested_max_messages=200,
                requested_date_window=None,
                relationship_marked=True,
                relationship_approved=True,
                legal_marked=False,
                decision_approved=True,
            ),
            context=proposal.context,
            conversation_summary=proposal.conversation_summary,
            source_readiness=proposal.source_readiness,
        )

    monkeypatch.setattr(spark_drafts, "load_imessage_target_preview", fake_preview)

    response = await spark_drafts.spark_imessage_target_preview(
        _request(),
        principal_id="ken",
        approval_id="ken-imessage-approved-20260605-001",
        limit=50,
        _="user",
    )

    payload = response.model_dump()
    assert payload["label"] == "Sweta"
    assert payload["context_messages_read"] == 2
    assert payload["conversation_summary"]["last_message_preview"] == (
        "private inbound body"
    )
    assert payload["context_preview"] == [
        {
            "index": 1,
            "speaker": "Other",
            "is_from_me": False,
            "message_ref_hash": "msg-1",
            "body_text": "private inbound body",
        },
        {
            "index": 2,
            "speaker": "Ken",
            "is_from_me": True,
            "message_ref_hash": "msg-2",
            "body_text": "ken sent private body",
        },
    ]
    logs = json.dumps(fake_logger.infos).lower()
    assert "spark_imessage_target_preview_loaded" in logs
    assert "private inbound body" not in logs
    assert "ken sent private body" not in logs
    assert "sweta" not in logs


@pytest.mark.asyncio
async def test_spark_imessage_draft_returns_review_payload_and_safe_logs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_logger = _FakeLogger()
    personality_rows = [
        {
            "kind": "relationship",
            "content": "Sweta: partner; default hybrid_review; approval required True.",
        }
    ]
    monkeypatch.setattr(spark_drafts, "logger", fake_logger)
    _stub_personality_memory(monkeypatch, personality_rows)

    async def fake_create(**kwargs):
        assert kwargs == {
            "principal_id": "ken",
            "approval_id": None,
            "reply_goal": "Tell her I am on it",
            "max_context_messages": 10,
            "style_adjustments": [],
            "personality_memory_rows": personality_rows,
            "target_memory_rows": [],
        }
        return _proposal()

    monkeypatch.setattr(spark_drafts, "create_imessage_draft_proposal", fake_create)

    response = await spark_drafts.spark_imessage_draft(
        _request(),
        spark_drafts.SparkIMessageDraftRequest(
            reply_goal="Tell her I am on it",
            max_context_messages=10,
        ),
        "user",
    )

    payload = response.model_dump()
    assert payload["draft_text"] == "Tell her I am on it."
    assert payload["can_send"] is False
    assert payload["requires_human_approval"] is True
    assert payload["body_access"] is True
    assert payload["context_messages_read"] == 2
    assert payload["conversation_summary"] == {
        "channel": "iMessage",
        "voice_principal_label": "Ken",
        "reply_target_label": "Sweta",
        "reply_target_confidence": "approved_source_label",
        "context_order": "newest_first",
        "last_message_speaker": None,
        "last_message_preview": None,
        "last_message_ref_hash": None,
    }
    assert payload["draft_quality"]["score"] == 100
    assert payload["source_readiness"][0]["status"] == "live_runtime_context"
    assert payload["context_preview"] == []
    assert payload["personality_memory_preview"] == []
    assert payload["target_memory_preview"] == []
    assert fake_logger.infos == [
        (
            "spark_imessage_draft_proposed",
            {
                "event": "spark_imessage_draft_proposed",
                "component": "spark_drafts",
                "action": "imessage_draft",
                "body_access": True,
                "can_send": False,
                "requires_human_approval": True,
                "context_messages_read": 2,
                "principal_sent_messages": 1,
                "runtime_context_messages": 1,
                "approval_ref_hash": "approval-hash",
                "source_reference_hash": "source-hash",
                "chat_guid_hash": "chat-hash",
                "draft_engine": "deterministic_v0",
                "style_adjustment_count": 0,
                "detected_sensitivity": [],
                "blocked_sensitivity_count": 0,
                "actor_sub": "spark-service",
                "actor_type": "service",
                "actor_iss": "spark",
                "scopes_used": ["spark.draft", "imessage.read"],
                "risk_tier": "T2",
            },
        )
    ]
    logs = json.dumps(fake_logger.infos).lower()
    assert "private inbound body" not in logs
    assert "approved-chat-guid" not in logs


@pytest.mark.asyncio
async def test_spark_imessage_draft_can_return_runtime_review_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_logger = _FakeLogger()
    personality_rows = [
        {
            "kind": "style",
            "content": "Ken prefers short bullets when timing matters.",
            "source": "spark_approved",
            "evidence_ref_hash": "memory-hash",
        },
        {
            "kind": "boundary",
            "content": "Relationship topics require Spark review before action.",
            "source": "spark_vault",
        },
    ]
    monkeypatch.setattr(spark_drafts, "logger", fake_logger)
    _stub_personality_memory(monkeypatch, personality_rows)

    async def fake_create(**kwargs):
        assert kwargs == {
            "principal_id": "ken",
            "approval_id": None,
            "reply_goal": "Show me context",
            "max_context_messages": 10,
            "style_adjustments": [],
            "personality_memory_rows": personality_rows,
            "target_memory_rows": [],
        }
        return _proposal()

    monkeypatch.setattr(spark_drafts, "create_imessage_draft_proposal", fake_create)

    response = await spark_drafts.spark_imessage_draft(
        _request(),
        spark_drafts.SparkIMessageDraftRequest(
            reply_goal="Show me context",
            max_context_messages=10,
            include_context_preview=True,
            include_memory_preview=True,
        ),
        "user",
    )

    payload = response.model_dump()
    assert payload["context_preview"] == [
        {
            "index": 1,
            "speaker": "Other",
            "is_from_me": False,
            "message_ref_hash": "msg-1",
            "body_text": "private inbound body",
        },
        {
            "index": 2,
            "speaker": "Ken",
            "is_from_me": True,
            "message_ref_hash": "msg-2",
            "body_text": "ken sent private body",
        },
    ]
    assert payload["conversation_summary"]["reply_target_label"] == "Sweta"
    assert payload["conversation_summary"]["last_message_speaker"] == "Other"
    assert payload["conversation_summary"]["last_message_preview"] == (
        "private inbound body"
    )
    assert payload["personality_memory_preview"] == [
        {
            "kind": "style",
            "content": "Ken prefers short bullets when timing matters.",
            "source": "spark_approved",
            "evidence_ref_hash": "memory-hash",
            "reason": None,
        }
    ]
    assert payload["target_memory_preview"] == []
    logs = json.dumps(fake_logger.infos).lower()
    assert "private inbound body" not in logs
    assert "ken sent private body" not in logs
    assert "short bullets" not in logs


@pytest.mark.asyncio
async def test_spark_imessage_draft_failure_log_omits_exception_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_logger = _FakeLogger()
    monkeypatch.setattr(spark_drafts, "logger", fake_logger)
    _stub_personality_memory(monkeypatch)

    async def fake_create(**kwargs):
        raise SparkDraftContextError(
            "password=secret private inbound body contact=private-name"
        )

    monkeypatch.setattr(spark_drafts, "create_imessage_draft_proposal", fake_create)

    with pytest.raises(HTTPException) as exc_info:
        await spark_drafts.spark_imessage_draft(
            _request(),
            spark_drafts.SparkIMessageDraftRequest(),
            "user",
        )

    assert exc_info.value.status_code == 502
    assert fake_logger.warnings == [
        (
            "spark_imessage_draft_failed",
            {
                "event": "spark_imessage_draft_failed",
                "component": "spark_drafts",
                "action": "imessage_draft",
                "body_access": False,
                "error_class": "SparkDraftContextError",
                "status_code": 502,
                "actor_sub": "spark-service",
                "actor_type": "service",
                "actor_iss": "spark",
                "scopes_used": ["spark.draft", "imessage.read"],
                "risk_tier": "T2",
            },
        )
    ]
    logs = json.dumps(fake_logger.warnings)
    assert "password=secret" not in logs
    assert "private inbound body" not in logs
    assert "private-name" not in logs


@pytest.mark.asyncio
async def test_spark_imessage_draft_approval_queues_safe_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_logger = _FakeLogger()
    monkeypatch.setattr(spark_drafts, "logger", fake_logger)
    fake_conn = _stub_personality_memory(monkeypatch)

    async def fake_create(**kwargs):
        assert kwargs == {
            "principal_id": "ken",
            "approval_id": None,
            "reply_goal": "Tell her I am on it",
            "max_context_messages": 10,
            "style_adjustments": [],
            "personality_memory_rows": [],
            "target_memory_rows": [],
        }
        return _proposal()

    async def fake_enqueue(conn, **kwargs):
        assert conn is fake_conn
        assert kwargs["actor_sub"] == "spark-service"
        assert kwargs["actor_type"] == "service"
        assert isinstance(kwargs["nonce"], str)
        assert kwargs["proposal"].draft_text == "Edited draft"
        assert kwargs["proposal"].draft_engine == "human_override"
        return UUID("11111111-1111-4111-8111-111111111111")

    crypto_token = object()
    outbox_calls: list[dict[str, object]] = []

    async def fake_create_outbox(conn, **kwargs):
        assert conn is fake_conn
        outbox_calls.append(kwargs)
        assert kwargs["proposal"].draft_text == "Edited draft"
        assert kwargs["approval_queue_id"] == UUID(
            "11111111-1111-4111-8111-111111111111"
        )
        assert kwargs["actor_sub"] == "spark-service"
        assert kwargs["actor_type"] == "service"
        assert kwargs["crypto"] is crypto_token
        return spark_drafts.SparkOutboxCreateResult(
            outbox_id="22222222-2222-4222-8222-222222222222",
            status="pending_approval",
            draft_text_hash="hmac-sha256:" + "a" * 64,
            created=True,
        )

    feedback_calls: list[dict[str, object]] = []

    def fake_feedback(**kwargs):
        feedback_calls.append(kwargs)
        assert kwargs["original_proposal"].draft_text == "Tell her I am on it."
        assert kwargs["edited_proposal"].draft_text == "Edited draft"
        return SparkDraftEditFeedbackResult(
            recorded=True,
            feedback_ref_hash="feedback-hash",
            candidate_key_phrases=("Edited draft",),
            calibration_lessons=("Prefer shorter text drafts.",),
        )

    monkeypatch.setattr(spark_drafts, "create_imessage_draft_proposal", fake_create)
    monkeypatch.setattr(spark_drafts, "enqueue_spark_draft_approval", fake_enqueue)
    monkeypatch.setattr(spark_drafts, "load_spark_outbox_crypto", lambda: crypto_token)
    monkeypatch.setattr(spark_drafts, "create_spark_outbox_item", fake_create_outbox)
    monkeypatch.setattr(spark_drafts, "record_spark_draft_edit_feedback", fake_feedback)

    response = await spark_drafts.spark_imessage_draft_approval_request(
        _request(),
        spark_drafts.SparkIMessageDraftApprovalRequest(
            reply_goal="Tell her I am on it",
            max_context_messages=10,
            draft_text_override="Edited draft",
        ),
        "user",
    )

    payload = response.model_dump()
    assert payload["draft_text"] == "Edited draft"
    assert payload["queue_id"] == "11111111-1111-4111-8111-111111111111"
    assert payload["approval_status"] == "pending"
    assert payload["outbox_id"] == "22222222-2222-4222-8222-222222222222"
    assert payload["outbox_status"] == "pending_approval"
    assert payload["outbox_text_hash"] == "hmac-sha256:" + "a" * 64
    assert payload["outbox_recorded"] is True
    assert payload["voice_feedback_recorded"] is True
    assert payload["voice_feedback_ref_hash"] == "feedback-hash"
    assert payload["candidate_key_phrases"] == ["Edited draft"]
    assert payload["calibration_lessons"] == ["Prefer shorter text drafts."]
    assert len(feedback_calls) == 1
    assert len(outbox_calls) == 1
    logs = json.dumps(fake_logger.infos).lower()
    assert "spark_imessage_draft_approval_queued" in logs
    assert "edited draft" not in logs
    assert "22222222-2222-4222-8222-222222222222" in logs
    assert "feedback-hash" in logs
    assert "calibration_lesson_count" in logs
    assert "private inbound body" not in logs
    assert "approved-chat-guid" not in logs


@pytest.mark.asyncio
async def test_spark_imessage_draft_feedback_records_label_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_logger = _FakeLogger()
    feedback_calls: list[dict[str, object]] = []
    monkeypatch.setattr(spark_drafts, "logger", fake_logger)

    def fake_feedback(**kwargs):
        feedback_calls.append(kwargs)
        return spark_drafts.SparkDraftQualityFeedbackResult(
            recorded=True,
            feedback_ref_hash="feedback-hash",
            feedback_label="out_of_context",
        )

    monkeypatch.setattr(
        spark_drafts,
        "record_spark_draft_quality_feedback",
        fake_feedback,
    )

    response = await spark_drafts.spark_imessage_draft_feedback(
        _request(),
        spark_drafts.SparkIMessageDraftFeedbackRequest(
            principal_id="ken",
            feedback_label="out_of_context",
            draft_version="spark-imessage-draft/v0",
            approval_ref_hash="approval-hash",
            source_reference_hash="source-hash",
            chat_guid_hash="chat-hash",
        ),
        "user",
    )

    assert response.status == "recorded"
    assert response.feedback_recorded is True
    assert response.feedback_label == "out_of_context"
    assert feedback_calls == [
        {
            "principal_id": "ken",
            "feedback_label": "out_of_context",
            "draft_version": "spark-imessage-draft/v0",
            "approval_ref_hash": "approval-hash",
            "source_reference_hash": "source-hash",
            "chat_guid_hash": "chat-hash",
        }
    ]
    logs = json.dumps(fake_logger.infos).lower()
    assert "out_of_context" in logs
    assert "draft_text" not in logs
    assert "private inbound body" not in logs


@pytest.mark.asyncio
async def test_spark_imessage_outbox_lists_metadata_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_logger = _FakeLogger()
    fake_conn = object()
    monkeypatch.setattr(spark_drafts, "logger", fake_logger)
    monkeypatch.setattr(
        spark_drafts,
        "rls_connection",
        lambda request: _AsyncContext(fake_conn),
    )

    async def fake_list(conn, **kwargs):
        assert conn is fake_conn
        assert kwargs == {"principal_id": "ken", "limit": 25}
        return (
            SparkOutboxListItem(
                outbox_id="22222222-2222-4222-8222-222222222222",
                channel="imessage",
                principal_id="ken",
                target_label="Sweta",
                approval_queue_id="11111111-1111-4111-8111-111111111111",
                draft_text_hash="hmac-sha256:" + "a" * 64,
                status="pending_approval",
                send_attempt_count=0,
                created_at=datetime.fromisoformat("2026-06-15T20:00:00+00:00"),
                updated_at=datetime.fromisoformat("2026-06-15T20:01:00+00:00"),
                sent_at=None,
            ),
        )

    monkeypatch.setattr(spark_drafts, "list_spark_outbox_items", fake_list)

    response = await spark_drafts.spark_imessage_outbox_items(
        _request(),
        principal_id="ken",
        limit=25,
    )

    payload = response.model_dump()
    assert payload["principal_id"] == "ken"
    assert payload["items"][0]["target_label"] == "Sweta"
    assert payload["items"][0]["draft_text_hash"].startswith("hmac-sha256:")
    serialized = json.dumps(payload).lower()
    assert '"draft_text":' not in serialized
    assert "private inbound body" not in serialized
    logs = json.dumps(fake_logger.infos).lower()
    assert "spark_imessage_outbox_listed" in logs
    assert "body_access" in logs
    assert "private inbound body" not in logs


@pytest.mark.asyncio
async def test_spark_imessage_send_approved_outbox_executes_safe_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_logger = _FakeLogger()
    fake_conn = object()
    outbox_id = UUID("22222222-2222-4222-8222-222222222222")
    crypto_token = object()
    send_calls: list[dict[str, object]] = []
    monkeypatch.setattr(spark_drafts, "logger", fake_logger)
    monkeypatch.setattr(
        spark_drafts,
        "rls_connection",
        lambda request: _AsyncContext(fake_conn),
    )
    monkeypatch.setattr(spark_drafts, "load_spark_outbox_crypto", lambda: crypto_token)

    async def fake_send(conn, **kwargs):
        assert conn is fake_conn
        send_calls.append(kwargs)
        assert kwargs["outbox_id"] == outbox_id
        assert kwargs["actor_sub"] == "spark-service"
        assert kwargs["actor_type"] == "service"
        assert kwargs["crypto"] is crypto_token
        return spark_drafts.SparkOutboxSendResult(
            outbox_id=str(outbox_id),
            outbox_status="sent",
            approval_queue_id="11111111-1111-4111-8111-111111111111",
            approval_status="executed",
            message_ref_hash="message-hash",
            send_attempt_count=1,
        )

    monkeypatch.setattr(
        spark_drafts,
        "send_approved_spark_imessage_outbox",
        fake_send,
    )

    response = await spark_drafts.spark_imessage_send_approved_outbox(
        _request(["spark.draft", "imessage.send"]),
        outbox_id,
        "user",
    )

    assert response.outbox_status == "sent"
    assert response.approval_status == "executed"
    assert response.message_ref_hash == "message-hash"
    assert len(send_calls) == 1
    logs = json.dumps(fake_logger.infos).lower()
    assert "spark_imessage_approved_send_executed" in logs
    assert "imessage.send" in logs
    assert "t4" in logs
    assert "private inbound body" not in logs
    assert "approved-chat-guid" not in logs
    assert "edited draft" not in logs
    assert "draft_text" not in logs


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


class _AsyncContext:
    def __init__(self, value: object) -> None:
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, exc_type, exc, tb):
        return False
