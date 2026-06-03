from datetime import datetime, timedelta, timezone
from uuid import uuid4

from brain.agents.warden import (
    DEFAULT_MANAGED_AGENTS,
    SupervisedAgent,
    managed_agent_ids,
    supervision_event,
    supervision_findings,
    supervision_signature,
    supervision_snapshot,
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


def test_warden_default_managed_agents_include_ledger():
    assert "ledger" in DEFAULT_MANAGED_AGENTS
    assert managed_agent_ids({}) == DEFAULT_MANAGED_AGENTS
