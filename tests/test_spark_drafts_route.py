from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException

from brain.middleware.approval_classes import classify_route, determine_risk_tier
from brain.routes import spark_drafts
from brain.services.spark_imessage_drafts import (
    SparkDraftContext,
    SparkDraftContextError,
    SparkDraftProposal,
    SparkRuntimeMessage,
)
from brain.services.spark_voice_feedback import SparkDraftEditFeedbackResult


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
    classes = classify_route("POST", "/v1/spark/drafts/imessage")

    assert classes == ["write", "security_write"]
    assert determine_risk_tier(classes) == "T2"

    approval_classes = classify_route(
        "POST", "/v1/spark/drafts/imessage/approval-request"
    )
    feedback_classes = classify_route("POST", "/v1/spark/drafts/imessage/feedback")
    assert approval_classes == ["write", "security_write"]
    assert determine_risk_tier(approval_classes) == "T2"
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
            "personality_memory_rows": personality_rows,
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
    assert payload["context_preview"] == []
    assert payload["personality_memory_preview"] == []
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
            "personality_memory_rows": personality_rows,
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
    assert payload["personality_memory_preview"] == [
        {
            "kind": "style",
            "content": "Ken prefers short bullets when timing matters.",
            "source": "spark_approved",
            "evidence_ref_hash": "memory-hash",
        }
    ]
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
            "personality_memory_rows": [],
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

    feedback_calls: list[dict[str, object]] = []

    def fake_feedback(**kwargs):
        feedback_calls.append(kwargs)
        assert kwargs["original_proposal"].draft_text == "Tell her I am on it."
        assert kwargs["edited_proposal"].draft_text == "Edited draft"
        return SparkDraftEditFeedbackResult(
            recorded=True,
            feedback_ref_hash="feedback-hash",
            candidate_key_phrases=("Edited draft",),
        )

    monkeypatch.setattr(spark_drafts, "create_imessage_draft_proposal", fake_create)
    monkeypatch.setattr(spark_drafts, "enqueue_spark_draft_approval", fake_enqueue)
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
    assert payload["voice_feedback_recorded"] is True
    assert payload["voice_feedback_ref_hash"] == "feedback-hash"
    assert payload["candidate_key_phrases"] == ["Edited draft"]
    assert len(feedback_calls) == 1
    logs = json.dumps(fake_logger.infos).lower()
    assert "spark_imessage_draft_approval_queued" in logs
    assert "edited draft" not in logs
    assert "feedback-hash" in logs
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
            feedback_label="too_formal",
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
            feedback_label="too_formal",
            draft_version="spark-imessage-draft/v0",
            approval_ref_hash="approval-hash",
            source_reference_hash="source-hash",
            chat_guid_hash="chat-hash",
        ),
        "user",
    )

    assert response.status == "recorded"
    assert response.feedback_recorded is True
    assert response.feedback_label == "too_formal"
    assert feedback_calls == [
        {
            "principal_id": "ken",
            "feedback_label": "too_formal",
            "draft_version": "spark-imessage-draft/v0",
            "approval_ref_hash": "approval-hash",
            "source_reference_hash": "source-hash",
            "chat_guid_hash": "chat-hash",
        }
    ]
    logs = json.dumps(fake_logger.infos).lower()
    assert "too_formal" in logs
    assert "draft_text" not in logs
    assert "private inbound body" not in logs


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
        warnings=("draft_only_no_send",),
    )


class _AsyncContext:
    def __init__(self, value: object) -> None:
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, exc_type, exc, tb):
        return False
