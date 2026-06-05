from __future__ import annotations

from types import SimpleNamespace

import pytest

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
