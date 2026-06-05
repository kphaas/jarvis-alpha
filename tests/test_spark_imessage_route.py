from __future__ import annotations

from types import SimpleNamespace

import pytest

from brain.middleware.approval_classes import classify_route, determine_risk_tier
from brain.routes import spark_imessage
from brain.services.bluebubbles_client import (
    BlueBubblesCounts,
    BlueBubblesHealth,
    BlueBubblesRecentChatMetadata,
)


def _request(scopes: list[str] | None = None):
    return SimpleNamespace(
        state=SimpleNamespace(
            actor_type="service",
            role=None,
            scopes=scopes or ["imessage.read"],
            iss="spark",
        )
    )


def test_spark_imessage_routes_are_classified_t2_security_reads() -> None:
    for path in (
        "/v1/spark/imessage/health",
        "/v1/spark/imessage/counts",
        "/v1/spark/imessage/recent-chats/metadata",
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
