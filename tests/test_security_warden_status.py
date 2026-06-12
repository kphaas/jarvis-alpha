from datetime import UTC, datetime, timedelta

from brain.agents.warden import DEFAULT_MANAGED_AGENTS
from brain.routes.security import SECURITY_MANAGED_AGENT_IDS, _warden_hardening_state
from brain.routes import security


def test_security_warden_status_managed_ids_match_warden_defaults():
    assert SECURITY_MANAGED_AGENT_IDS == ("warden", *DEFAULT_MANAGED_AGENTS)


def test_warden_hardening_state_uses_registry_metadata():
    result = _warden_hardening_state(
        {
            "metadata": {
                "active_network_hardening": "service_tls_cert_renewal",
                "next_network_hardening": "service_tls_cert_renewal",
            }
        },
        [
            {
                "agent_id": "sweep",
                "metadata": {"active_hardening": "service_tls_cert_renewal"},
            }
        ],
    )

    assert result == {
        "active_hardening": "service_tls_cert_renewal",
        "next_hardening": "service_tls_cert_renewal",
    }


def test_warden_hardening_state_falls_back_to_sweep_metadata():
    result = _warden_hardening_state(
        None,
        [
            {
                "agent_id": "sweep",
                "metadata": {"active_hardening": "service_tls_cert_renewal"},
            }
        ],
    )

    assert result == {
        "active_hardening": "service_tls_cert_renewal",
        "next_hardening": "service_tls_cert_renewal",
    }


def test_sweep_report_summary_marks_missing_and_stale_nodes():
    now = datetime(2026, 6, 12, 18, 0, tzinfo=UTC)
    rows = [
        {
            "node": "brain",
            "payload": {
                "node": "brain",
                "fqdn": "jarvis-brain.tail40ed36.ts.net",
                "status": "ok",
                "days_remaining": 85,
                "health_ok": True,
                "threshold_days": 30,
            },
            "severity": "info",
            "title": "Sweep TLS report: brain",
            "message": "ok",
            "notification_status": "skipped",
            "created_at": now - timedelta(minutes=5),
        },
        {
            "node": "sandbox",
            "payload": {
                "node": "sandbox",
                "fqdn": "jarvis-sandbox.tail40ed36.ts.net",
                "status": "ok",
                "days_remaining": 44,
                "health_ok": True,
                "threshold_days": 30,
            },
            "severity": "info",
            "title": "Sweep TLS report: sandbox",
            "message": "ok",
            "notification_status": "skipped",
            "created_at": now - timedelta(hours=25),
        },
    ]

    summary = security._sweep_report_summary(rows, now=now)

    assert summary["received"] == 2
    assert summary["attention"] == 3
    by_node = {report["node"]: report for report in summary["reports"]}
    assert by_node["brain"]["is_stale"] is False
    assert by_node["sandbox"]["is_stale"] is True
    assert by_node["endpoint"]["status"] == "missing"
    assert by_node["gateway"]["status"] == "missing"
