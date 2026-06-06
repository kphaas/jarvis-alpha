from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from brain.middleware.approval_classes import classify_route, determine_risk_tier
from brain.routes import spark_persona
from brain.services.spark_persona_guardrails import default_spark_guardrails


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
    write_classes = classify_route("PUT", "/v1/spark/persona/guardrails")

    assert read_classes == ["read", "security_read"]
    assert write_classes == ["write", "security_write"]
    assert determine_risk_tier(read_classes) == "T2"
    assert determine_risk_tier(write_classes) == "T2"


@pytest.mark.asyncio
async def test_spark_guardrails_read_requires_spark_scope() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await spark_persona.get_spark_guardrails(
            _request(scopes=["imessage.read"]), "user"
        )

    assert exc_info.value.status_code == 403


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
