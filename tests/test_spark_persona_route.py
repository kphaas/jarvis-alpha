from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from brain.middleware.approval_classes import classify_route, determine_risk_tier
from brain.routes import spark_persona
from brain.services.auto_brain import (
    AutoBrainSourceMetadata,
    AutoSparkContextMetadata,
    AutoSparkRuntimeMode,
)
from brain.services.spark_persona_guardrails import default_spark_guardrails
from brain.services.spark_personality_memory import SparkPersonalityMemoryProposal


def _request(*, role: str | None = None, scopes: list[str] | None = None):
    return SimpleNamespace(
        state=SimpleNamespace(
            actor_type="user" if role else "service",
            role=role,
            user_id="ken" if role else "spark-service",
            scopes=scopes or [],
            iss="user" if role else "spark",
        )
    )


class _FakeLogger:
    def __init__(self) -> None:
        self.infos: list[tuple[str, dict[str, object]]] = []

    def info(self, message: str, *, extra: dict[str, object]) -> None:
        self.infos.append((message, extra))


def test_spark_persona_routes_are_classified_t2_security_state() -> None:
    read_classes = classify_route("GET", "/v1/spark/persona/guardrails")
    auto_context_classes = classify_route("GET", "/v1/spark/persona/auto-context")
    memory_read_classes = classify_route("GET", "/v1/spark/persona/memory")
    write_classes = classify_route("PUT", "/v1/spark/persona/guardrails")
    memory_propose_classes = classify_route("POST", "/v1/spark/persona/memory/propose")
    memory_write_classes = classify_route("POST", "/v1/spark/persona/memory/approve")
    memory_archive_classes = classify_route("POST", "/v1/spark/persona/memory/archive")
    memory_reject_classes = classify_route("POST", "/v1/spark/persona/memory/reject")

    assert read_classes == ["read", "security_read"]
    assert auto_context_classes == ["read", "security_read"]
    assert memory_read_classes == ["read", "security_read"]
    assert write_classes == ["write", "security_write"]
    assert memory_propose_classes == ["write", "security_write"]
    assert memory_write_classes == ["write", "security_write"]
    assert memory_archive_classes == ["write", "security_write"]
    assert memory_reject_classes == ["write", "security_write"]
    assert determine_risk_tier(read_classes) == "T2"
    assert determine_risk_tier(auto_context_classes) == "T2"
    assert determine_risk_tier(memory_read_classes) == "T2"
    assert determine_risk_tier(write_classes) == "T2"
    assert determine_risk_tier(memory_propose_classes) == "T2"
    assert determine_risk_tier(memory_write_classes) == "T2"
    assert determine_risk_tier(memory_archive_classes) == "T2"
    assert determine_risk_tier(memory_reject_classes) == "T2"


@pytest.mark.asyncio
async def test_spark_guardrails_read_requires_spark_scope() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await spark_persona.get_spark_guardrails(
            _request(scopes=["imessage.read"]), "user"
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_spark_auto_context_route_returns_metadata_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_logger = _FakeLogger()
    context = AutoSparkContextMetadata(
        version="0.1.0",
        allowed_for=["spark-draft"],
        source_count=1,
        rule_count=2,
        sources=[
            AutoBrainSourceMetadata(
                path="auto/mission.md",
                sha256="0" * 64,
                byte_count=42,
                heading="Auto Mission",
            )
        ],
        runtime_mode=AutoSparkRuntimeMode(
            spark_can_read=True,
            spark_can_write=False,
            durable_memory_writes=False,
            outbound_send_allowed=False,
        ),
    )
    monkeypatch.setattr(spark_persona, "logger", fake_logger)
    monkeypatch.setattr(spark_persona, "load_auto_spark_context", lambda: context)

    response = await spark_persona.get_spark_auto_context(
        _request(scopes=["spark.draft"]),
        "user",
    )

    assert response.body_access is False
    assert response.raw_content_returned is False
    assert response.sources[0].path == "auto/mission.md"
    logs = json.dumps(fake_logger.infos).lower()
    assert "private body" not in logs
    assert "raw_content_returned" in logs


@pytest.mark.asyncio
async def test_spark_guardrails_read_returns_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = default_spark_guardrails()
    monkeypatch.setattr(spark_persona, "load_spark_guardrails", lambda: state)

    response = await spark_persona.get_spark_guardrails(
        _request(scopes=["spark.draft"]),
        "user",
    )

    assert response.auto_send_enabled is False
    assert response.protected_relationships[0].id == "ryleigh"


@pytest.mark.asyncio
async def test_spark_guardrails_write_requires_admin() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await spark_persona.put_spark_guardrails(
            _request(scopes=["spark.draft"]),
            default_spark_guardrails(),
            "user",
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_spark_guardrails_write_logs_only_safe_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_logger = _FakeLogger()
    state = default_spark_guardrails()
    monkeypatch.setattr(spark_persona, "logger", fake_logger)
    monkeypatch.setattr(spark_persona, "save_spark_guardrails", lambda payload: payload)

    response = await spark_persona.put_spark_guardrails(
        _request(role="admin"),
        state,
        "user",
    )

    assert response.auto_send_enabled is False
    assert fake_logger.infos == [
        (
            "spark_guardrails_updated",
            {
                "event": "spark_guardrails_updated",
                "component": "spark_persona",
                "principal_id": "ken",
                "active_mode": "draft_only",
                "auto_send_enabled": False,
                "protected_topic_count": 7,
                "protected_relationship_count": 5,
                "actor_sub": "ken",
                "actor_type": "user",
            },
        )
    ]
    logs = json.dumps(fake_logger.infos)
    assert "private inbound body" not in logs
    assert "draft_text" not in logs


@pytest.mark.asyncio
async def test_spark_memory_read_requires_admin_scope() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await spark_persona.get_spark_personality_memory(
            _request(scopes=["spark.draft"]),
            "ken",
            "user",
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_spark_memory_read_returns_active_and_proposals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_logger = _FakeLogger()
    rows = [
        {
            "id": "memory-1",
            "principal_id": "ken",
            "kind": "voice",
            "content": "Voice should feel composed.",
            "source": "spark_approved",
            "evidence_ref_hash": None,
            "importance_score": 0.9,
            "approved_by": "ken",
            "approved_at": None,
            "created_at": None,
            "updated_at": None,
        }
    ]
    proposal = SparkPersonalityMemoryProposal(
        proposal_id="proposal-123",
        principal_id="ken",
        kind="phrase",
        content="Signature phrase: fair enough.",
        source="spark_feedback",
        reason="human-edited Spark draft feedback",
        confidence=0.65,
        evidence_ref_hash="a" * 64,
    )
    monkeypatch.setattr(spark_persona, "logger", fake_logger)
    monkeypatch.setattr(
        spark_persona,
        "rls_connection",
        lambda _request: _AsyncConn(rows=rows),
    )
    monkeypatch.setattr(
        spark_persona,
        "load_spark_guardrails",
        default_spark_guardrails,
    )
    monkeypatch.setattr(
        spark_persona,
        "fetch_personality_memory",
        _async_return(rows),
    )
    monkeypatch.setattr(
        spark_persona,
        "build_personality_memory_proposals",
        lambda **_kwargs: (proposal,),
    )

    response = await spark_persona.get_spark_personality_memory(
        _request(role="admin"),
        "ken",
        "user",
    )

    assert response.active[0].content == "Voice should feel composed."
    assert response.proposals[0].content == "Signature phrase: fair enough."
    assert response.buddy["feedback_phrase_count"] == 1
    logs = json.dumps(fake_logger.infos)
    assert "draft_text" not in logs
    assert "private inbound body" not in logs


@pytest.mark.asyncio
async def test_spark_memory_approval_requires_admin() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await spark_persona.approve_spark_personality_memory(
            _request(scopes=["spark.draft"]),
            spark_persona.SparkPersonalityMemoryApproveRequest(
                proposal_id="proposal-123",
                kind="phrase",
                content="Signature phrase: cheers.",
                source="spark_feedback",
            ),
            "user",
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_spark_memory_propose_requires_admin() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await spark_persona.propose_spark_personality_memory(
            _request(scopes=["spark.draft"]),
            spark_persona.SparkPersonalityMemoryProposeRequest(
                principal_id="ken",
                note="Remember that I prefer short bullets.",
            ),
            "user",
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_spark_memory_propose_returns_buddy_proposal_without_logging_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_logger = _FakeLogger()
    monkeypatch.setattr(spark_persona, "logger", fake_logger)

    response = await spark_persona.propose_spark_personality_memory(
        _request(role="admin"),
        spark_persona.SparkPersonalityMemoryProposeRequest(
            principal_id="ken",
            note="Remember that I prefer short bullets when timing matters.",
        ),
        "user",
    )

    assert response.status == "proposed"
    assert response.proposal is not None
    assert response.proposal.principal_id == "ken"
    assert response.proposal.kind == "style"
    assert response.proposal.source == "buddy_proposal"
    assert response.proposal.evidence_ref_hash
    logs = json.dumps(fake_logger.infos)
    assert "short bullets" not in logs
    assert "timing matters" not in logs
    assert "draft_text" not in logs
    assert "private inbound body" not in logs


@pytest.mark.asyncio
async def test_spark_memory_approval_calls_reviewed_writer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_logger = _FakeLogger()
    saved_calls: list[dict[str, object]] = []

    async def fake_save(_conn: object, **kwargs: object) -> dict[str, object]:
        saved_calls.append(kwargs)
        return {
            "saved": True,
            "personality_id": "memory-1",
            "principal_id": kwargs["principal_id"],
            "kind": kwargs["kind"],
            "source": kwargs["source"],
        }

    monkeypatch.setattr(spark_persona, "logger", fake_logger)
    monkeypatch.setattr(
        spark_persona,
        "rls_connection",
        lambda _request: _AsyncConn(rows=[]),
    )
    monkeypatch.setattr(spark_persona, "save_personality_memory", fake_save)

    response = await spark_persona.approve_spark_personality_memory(
        _request(role="admin"),
        spark_persona.SparkPersonalityMemoryApproveRequest(
            proposal_id="proposal-123",
            kind="phrase",
            content="Signature phrase: cheers.",
            source="spark_feedback",
            evidence_ref_hash="a" * 64,
            importance_score=0.7,
        ),
        "user",
    )

    assert response.status == "saved"
    assert saved_calls == [
        {
            "principal_id": "ken",
            "kind": "phrase",
            "content": "Signature phrase: cheers.",
            "source": "spark_feedback",
            "evidence_ref_hash": "a" * 64,
            "approved_by": "ken",
            "importance_score": 0.7,
        }
    ]
    logs = json.dumps(fake_logger.infos)
    assert "Signature phrase: cheers." not in logs
    assert "draft_text" not in logs


@pytest.mark.asyncio
async def test_spark_memory_archive_calls_reviewed_archiver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_logger = _FakeLogger()
    archive_calls: list[dict[str, object]] = []

    async def fake_archive(_conn: object, **kwargs: object) -> dict[str, object]:
        archive_calls.append(kwargs)
        return {
            "archived": True,
            "personality_id": kwargs["memory_id"],
            "principal_id": kwargs["principal_id"],
        }

    monkeypatch.setattr(spark_persona, "logger", fake_logger)
    monkeypatch.setattr(
        spark_persona,
        "rls_connection",
        lambda _request: _AsyncConn(rows=[]),
    )
    monkeypatch.setattr(spark_persona, "archive_personality_memory", fake_archive)

    response = await spark_persona.archive_spark_personality_memory(
        _request(role="admin"),
        spark_persona.SparkPersonalityMemoryArchiveRequest(
            principal_id="ken",
            memory_id="11111111-1111-4111-8111-111111111111",
        ),
        "user",
    )

    assert response.status == "archived"
    assert archive_calls == [
        {
            "principal_id": "ken",
            "memory_id": "11111111-1111-4111-8111-111111111111",
            "archived_by": "ken",
        }
    ]
    logs = json.dumps(fake_logger.infos)
    assert "draft_text" not in logs
    assert "private inbound body" not in logs


@pytest.mark.asyncio
async def test_spark_memory_reject_records_proposal_without_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_logger = _FakeLogger()
    reject_calls: list[dict[str, object]] = []

    def fake_reject(**kwargs: object) -> dict[str, object]:
        reject_calls.append(kwargs)
        return {
            "rejected": True,
            "proposal_id": kwargs["proposal_id"],
            "principal_id": kwargs["principal_id"],
        }

    monkeypatch.setattr(spark_persona, "logger", fake_logger)
    monkeypatch.setattr(
        spark_persona,
        "reject_personality_memory_proposal",
        fake_reject,
    )

    response = await spark_persona.reject_spark_personality_memory(
        _request(role="admin"),
        spark_persona.SparkPersonalityMemoryRejectRequest(
            principal_id="ken",
            proposal_id="abcdef123456",
        ),
        "user",
    )

    assert response.status == "rejected"
    assert reject_calls == [
        {
            "principal_id": "ken",
            "proposal_id": "abcdef123456",
            "rejected_by": "ken",
        }
    ]
    logs = json.dumps(fake_logger.infos)
    assert "Signature phrase" not in logs
    assert "draft_text" not in logs


class _AsyncConn:
    def __init__(self, *, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    async def __aenter__(self) -> "_AsyncConn":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


def _async_return(value: object):
    async def inner(*_args: object, **_kwargs: object) -> object:
        return value

    return inner
