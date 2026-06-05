from __future__ import annotations

import json
from types import SimpleNamespace

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


def test_spark_imessage_draft_route_is_classified_t2_write() -> None:
    classes = classify_route("POST", "/v1/spark/drafts/imessage")

    assert classes == ["write", "security_write"]
    assert determine_risk_tier(classes) == "T2"


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
async def test_spark_imessage_draft_returns_review_payload_and_safe_logs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_logger = _FakeLogger()
    monkeypatch.setattr(spark_drafts, "logger", fake_logger)

    async def fake_create(**kwargs):
        assert kwargs == {
            "principal_id": "ken",
            "approval_id": None,
            "reply_goal": "Tell her I am on it",
            "max_context_messages": 10,
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
async def test_spark_imessage_draft_failure_log_omits_exception_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_logger = _FakeLogger()
    monkeypatch.setattr(spark_drafts, "logger", fake_logger)

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
