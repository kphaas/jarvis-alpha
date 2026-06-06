from __future__ import annotations

from types import SimpleNamespace

import pytest

from brain.db import pool as db_pool
from brain.db import rls as db_rls
from brain.middleware.approval_classes import classify_route, determine_risk_tier
from brain.routes import security


def _request(scopes: list[str] | None = None):
    return SimpleNamespace(
        state=SimpleNamespace(
            actor_type="service",
            role="service",
            scopes=scopes or ["security_write"],
            iss="forge",
        )
    )


def test_sentinel_report_route_is_t2_security_write() -> None:
    classes = classify_route("POST", "/v1/security/sentinel-report")

    assert classes == ["write", "security_write"]
    assert determine_risk_tier(classes) == "T2"


def test_security_agent_events_route_is_t2_security_read() -> None:
    classes = classify_route("GET", "/v1/security/agent-events")

    assert classes == ["read", "security_read"]
    assert determine_risk_tier(classes) == "T2"


def test_sentinel_event_severity_from_counts() -> None:
    assert security._sentinel_event_severity({"critical": 1}) == "critical"
    assert security._sentinel_event_severity({"high": 1}) == "error"
    assert security._sentinel_event_severity({"medium": 1}) == "warning"
    assert security._sentinel_event_severity({"low": 4}) == "info"


@pytest.mark.asyncio
async def test_sentinel_report_emits_warden_event(monkeypatch) -> None:
    captured = {}

    async def fake_emit(event, *, pool=None):
        captured["event"] = event
        captured["pool"] = pool
        return SimpleNamespace(event_id="evt-1", notification_status="sent")

    monkeypatch.setattr(security, "emit_agent_event", fake_emit)
    monkeypatch.setattr(security, "get_pool", lambda: "pool")

    report = security.SentinelReportIn(
        repo_slug="kphaas/jarvis-forge",
        commit_sha="abcdef1234567890",
        branch="main",
        scan_id="scan-1",
        findings_total=2,
        severity_counts={"critical": 0, "high": 1, "medium": 1},
        finding_ids=["sec-1", "sec-2"],
        top_findings=[
            security.SentinelReportFinding(
                id="sec-1",
                severity="high",
                title="Unsafe auth fallback",
                file_path="server/app.py",
                start_line=42,
            )
        ],
    )

    response = await security.sentinel_report(_request(), report)

    assert response.accepted is True
    assert response.event_id == "evt-1"
    event = captured["event"]
    assert event.agent_id == "warden"
    assert event.event_type == "warden.sentinel_report"
    assert event.severity == "error"
    assert event.channel_key == "security_alerts"
    assert event.payload["source"] == "forge_sentinel"
    assert event.payload["finding_ids"] == ["sec-1", "sec-2"]
    assert "Unsafe auth fallback" in event.payload["top_findings"][0]["title"]


@pytest.mark.asyncio
async def test_security_agent_events_surfaces_warden_events(monkeypatch) -> None:
    captured = {}

    class FakeConn:
        async def fetch(self, query, *params):
            captured["query"] = query
            captured["params"] = params
            return [
                {
                    "id": "0e0be62e-3704-41bd-92d3-0adcf91ead69",
                    "agent_id": "warden",
                    "run_id": None,
                    "event_type": "warden.sentinel_report",
                    "severity": "info",
                    "title": "Sentinel scan: kphaas/jarvis-forge",
                    "message": "Sentinel scanned kphaas/jarvis-forge.",
                    "correlation_id": "sentinel:kphaas/jarvis-forge:abc:scan-1",
                    "channel_key": "security_alerts",
                    "notification_status": "sent",
                    "notification_error": None,
                    "payload": '{"source":"forge_sentinel"}',
                    "notification_result": "{}",
                    "created_at": "2026-06-05T19:26:12-04:00",
                    "notified_at": None,
                }
            ]

    class FakeContext:
        async def __aenter__(self):
            return FakeConn()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    def fake_platform_admin_connection(**kwargs):
        captured["context"] = kwargs
        return FakeContext()

    monkeypatch.setattr(db_pool, "get_pool", lambda: "pool")
    monkeypatch.setattr(
        db_rls, "platform_admin_connection", fake_platform_admin_connection
    )

    response = await security.security_agent_events(_request(["security_read"]))

    assert response.count == 1
    event = response.events[0]
    assert event.agent_id == "warden"
    assert event.event_type == "warden.sentinel_report"
    assert event.payload["source"] == "forge_sentinel"
    assert captured["context"]["audit_actor"] == "security_agent_events"
    assert captured["params"][0] == [
        "warden",
        "porchlight",
        "keyturner",
        "sweep",
        "tripwire",
        "ledger",
        "sentry",
    ]
