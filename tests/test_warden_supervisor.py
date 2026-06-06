from datetime import datetime, timedelta, timezone
from uuid import uuid4

from brain.agents.warden import (
    DEFAULT_MANAGED_AGENTS,
    SupervisedAgent,
    auto_ticket_candidates,
    managed_agent_ids,
    owner_routes,
    supervision_event,
    supervision_findings,
    supervision_signature,
    supervision_snapshot,
    weekly_security_brief,
)


def _agent(
    agent_id: str,
    role: str,
    *,
    enabled: bool = True,
    status: str = "active",
    last_run_at: datetime | None = None,
    last_event_severity: str | None = None,
    last_event_title: str | None = None,
) -> SupervisedAgent:
    return SupervisedAgent(
        agent_id=agent_id,
        display_name=agent_id.replace("_", " ").title(),
        enabled=enabled,
        status=status,
        cadence="30s",
        metadata={"warden_role": role},
        last_run_at=last_run_at,
        last_event_severity=last_event_severity,
        last_event_title=last_event_title,
    )


def test_supervision_flags_stale_sweep_and_attention_event():
    now = datetime(2026, 6, 3, 16, 0, tzinfo=timezone.utc)
    findings = supervision_findings(
        [
            _agent(
                "sweep",
                "network_sweep",
                last_run_at=now - timedelta(minutes=8),
            ),
            _agent(
                "tripwire",
                "honeypot_sensor",
                last_event_severity="warning",
                last_event_title="Tripwire honeypot hit",
            ),
        ],
        now=now,
    )

    codes = {finding["code"] for finding in findings}
    assert codes == {"scheduled_agent_stale", "last_event_attention"}


def test_supervision_signature_is_stable_without_timestamps():
    now = datetime(2026, 6, 3, 16, 0, tzinfo=timezone.utc)
    findings = [
        {
            "agent_id": "porchlight",
            "display_name": "Porchlight",
            "role": "posture_sweep",
            "severity": "warning",
            "code": "posture_sweep_never_seen",
            "detail": "no history",
        }
    ]
    first = supervision_snapshot([], findings, checked_at=now)
    second = supervision_snapshot([], findings, checked_at=now + timedelta(minutes=5))

    assert supervision_signature(first) == supervision_signature(second)


def test_supervision_event_uses_security_alerts_and_recovery_message():
    now = datetime(2026, 6, 3, 16, 0, tzinfo=timezone.utc)
    snapshot = supervision_snapshot(
        [_agent("tripwire", "honeypot_sensor")],
        [],
        checked_at=now,
    )
    event = supervision_event(
        snapshot,
        run_id=uuid4(),
        previous_signature="old",
    )

    assert event.agent_id == "warden"
    assert event.event_type == "warden.supervision"
    assert event.title == "Warden security crew recovered"
    assert event.severity == "info"
    assert event.channel_key == "security_alerts"


def test_warden_default_managed_agents_include_ledger_and_sentry():
    assert "ledger" in DEFAULT_MANAGED_AGENTS
    assert "sentry" in DEFAULT_MANAGED_AGENTS
    assert managed_agent_ids({}) == DEFAULT_MANAGED_AGENTS


def test_warden_snapshot_includes_routes_brief_and_ticket_candidates():
    now = datetime(2026, 6, 3, 16, 0, tzinfo=timezone.utc)
    findings = [
        {
            "agent_id": "porchlight",
            "display_name": "Porchlight",
            "role": "posture_sweep",
            "severity": "warning",
            "code": "posture_sweep_stale",
            "detail": "Porchlight last checked in too long ago.",
        }
    ]
    snapshot = supervision_snapshot(
        [_agent("porchlight", "posture_sweep")],
        findings,
        checked_at=now,
    )

    assert snapshot["owner_routes"][0]["owner_agent"] == "porchlight"
    assert snapshot["owner_routes"][0]["recommended_action"] == (
        "run_porchlight_and_verify_schedule"
    )
    assert snapshot["weekly_brief"]["owner_counts"] == {"porchlight": 1}
    assert snapshot["ticket_candidates"][0]["ticket_key"] == (
        "warden:porchlight:posture_sweep_stale"
    )


def test_warden_owner_routes_support_posture_controls():
    routes = owner_routes(
        [
            {
                "id": "tls.service_certs",
                "title": "Service certificate freshness",
                "owner_agent": "sweep",
                "category": "TLS and certificates",
                "status": "fail",
                "summary": "Shortest certificate expires in 14 days.",
            }
        ]
    )
    tickets = auto_ticket_candidates(routes)
    brief = weekly_security_brief(
        status="warning",
        managed_count=4,
        healthy_count=3,
        routes=routes,
        checked_at=datetime(2026, 6, 3, 16, 0, tzinfo=timezone.utc),
    )

    assert routes[0]["owner_agent"] == "sweep"
    assert routes[0]["severity"] == "error"
    assert tickets[0]["severity"] == "critical"
    assert brief["owner_counts"] == {"sweep": 1}
