from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from brain.middleware.approval_classes import classify_route, determine_risk_tier
from brain.routes import spark_imessage
from brain.services.bluebubbles_client import (
    BlueBubblesClientError,
    BlueBubblesCounts,
    BlueBubblesHealth,
    BlueBubblesRecentChatMetadata,
)
from brain.services.spark_runtime_readiness import (
    SparkRuntimeCheck,
    SparkRuntimeReadiness,
)


def _request(scopes: list[str] | None = None):
    return SimpleNamespace(
        state=SimpleNamespace(
            actor_type="service",
            role=None,
            user_id="spark-service",
            scopes=scopes or ["imessage.read"],
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


def test_spark_imessage_routes_are_classified_t2_security_reads() -> None:
    for path in (
        "/v1/spark/imessage/health",
        "/v1/spark/imessage/counts",
        "/v1/spark/imessage/recent-chats/metadata",
        "/v1/spark/imessage/readiness",
    ):
        classes = classify_route("GET", path)
        assert classes == ["read", "security_read"]
        assert determine_risk_tier(classes) == "T2"


@pytest.mark.asyncio
async def test_spark_imessage_route_returns_health_without_body_access(
    monkeypatch,
) -> None:
    class FakeClient:
        async def health(self):
            return BlueBubblesHealth(
                status="Success",
                computer_id="spark@jarvis-brain",
                os_version="26.5.1",
                server_version="1.9.9",
                private_api=False,
                proxy_service="Dynamic DNS",
                helper_connected=False,
                detected_icloud=True,
                detected_imessage=True,
            )

    monkeypatch.setattr(spark_imessage, "_client", lambda: FakeClient())

    response = await spark_imessage.spark_imessage_health(_request(), "user")

    assert response.status == "Success"
    assert response.body_access is False
    assert response.detected_imessage is True


@pytest.mark.asyncio
async def test_spark_imessage_readiness_returns_safe_metadata(monkeypatch) -> None:
    fake_logger = _FakeLogger()

    async def fake_readiness():
        return SparkRuntimeReadiness(
            principal_id="ken",
            ready=False,
            checks=[
                SparkRuntimeCheck(
                    name="approved_thread_binding",
                    status="failed",
                    detail="Approved thread binding secret is missing",
                )
            ],
        )

    monkeypatch.setattr(spark_imessage, "check_spark_runtime_readiness", fake_readiness)
    monkeypatch.setattr(spark_imessage, "logger", fake_logger)

    response = await spark_imessage.spark_imessage_readiness(_request(), "user")

    assert response.ready is False
    assert response.body_access is False
    assert response.checks[0].name == "approved_thread_binding"
    logs = json.dumps(fake_logger.infos).lower()
    assert "password" not in logs
    assert "chat_guid" not in logs


@pytest.mark.asyncio
async def test_spark_imessage_route_returns_counts_only(monkeypatch) -> None:
    class FakeClient:
        async def counts(self):
            return BlueBubblesCounts(
                total_chats=1218,
                imessage_chats=484,
                sms_chats=706,
                rcs_chats=28,
                sent_messages=3496,
            )

    monkeypatch.setattr(spark_imessage, "_client", lambda: FakeClient())

    response = await spark_imessage.spark_imessage_counts(_request(), "user")

    assert response.total_chats == 1218
    assert response.sent_messages == 3496
    assert response.body_access is False


@pytest.mark.asyncio
async def test_spark_imessage_counts_logs_safe_debug_fields(monkeypatch) -> None:
    class FakeClient:
        async def counts(self):
            return BlueBubblesCounts(
                total_chats=1218,
                imessage_chats=484,
                sms_chats=706,
                rcs_chats=28,
                sent_messages=3496,
            )

    fake_logger = _FakeLogger()
    monkeypatch.setattr(spark_imessage, "_client", lambda: FakeClient())
    monkeypatch.setattr(spark_imessage, "logger", fake_logger)

    await spark_imessage.spark_imessage_counts(_request(), "user")

    assert fake_logger.infos == [
        (
            "spark_imessage_counts_checked",
            {
                "event": "spark_imessage_counts_checked",
                "component": "spark_imessage",
                "action": "counts",
                "body_access": False,
                "actor_sub": "spark-service",
                "actor_type": "service",
                "actor_iss": "spark",
                "scopes_used": ["imessage.read"],
                "risk_tier": "T2",
                "total_chats": 1218,
                "imessage_chats": 484,
                "sms_chats": 706,
                "rcs_chats": 28,
                "sent_messages": 3496,
            },
        )
    ]
    assert "password" not in json.dumps(fake_logger.infos)
    assert "message_body" not in json.dumps(fake_logger.infos)
    assert "contact_name" not in json.dumps(fake_logger.infos)


@pytest.mark.asyncio
async def test_spark_imessage_route_returns_recent_metadata_only(monkeypatch) -> None:
    class FakeClient:
        async def recent_chat_metadata(self, *, limit: int, offset: int):
            assert limit == 5
            assert offset == 0
            return BlueBubblesRecentChatMetadata(
                status=200,
                message="Success",
                count=5,
                total=1218,
                offset=0,
                limit=5,
                data_count=5,
            )

    monkeypatch.setattr(spark_imessage, "_client", lambda: FakeClient())

    response = await spark_imessage.spark_imessage_recent_chat_metadata(
        _request(),
        "user",
        limit=5,
        offset=0,
    )

    assert response.total == 1218
    assert response.data_count == 5
    assert response.body_access is False


@pytest.mark.asyncio
async def test_spark_imessage_failure_log_omits_exception_text(monkeypatch) -> None:
    class FakeClient:
        async def counts(self):
            raise BlueBubblesClientError(
                "password=secret body=private-text contact=private-name",
                status_code=500,
            )

    fake_logger = _FakeLogger()
    monkeypatch.setattr(spark_imessage, "_client", lambda: FakeClient())
    monkeypatch.setattr(spark_imessage, "logger", fake_logger)

    with pytest.raises(HTTPException) as exc_info:
        await spark_imessage.spark_imessage_counts(_request(), "user")

    assert exc_info.value.status_code == 502
    assert fake_logger.warnings == [
        (
            "spark_imessage_counts_failed",
            {
                "event": "spark_imessage_counts_failed",
                "component": "spark_imessage",
                "action": "counts",
                "body_access": False,
                "error_class": "BlueBubblesClientError",
                "status_code": 502,
                "actor_sub": "spark-service",
                "actor_type": "service",
                "actor_iss": "spark",
                "scopes_used": ["imessage.read"],
                "risk_tier": "T2",
            },
        )
    ]
    logs = json.dumps(fake_logger.warnings)
    assert "password=secret" not in logs
    assert "private-text" not in logs
    assert "private-name" not in logs
