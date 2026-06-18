from __future__ import annotations

import plistlib
from pathlib import Path

from scripts import check_memory_observability as monitor


REPO_ROOT = Path(__file__).resolve().parents[1]
PLIST_TEMPLATE = (
    REPO_ROOT / "launchagents" / "com.jarvis.alpha.memory-observability.template.plist"
)
PULL_SCRIPT = REPO_ROOT / "scripts" / "jarvisalpha_pull.sh"


def test_memory_observability_metrics_pass_when_under_slo() -> None:
    metrics = {
        "pending_review": 0,
        "review_required_24h": 0,
        "stale_dream_reviewed_writes": 0,
        "dream_approval_mismatch_count": 0,
        "dream_executed_without_ledger": 0,
        "high_priority_buddy_events": 1,
        "dream_approved_waiting_execution": 5,
    }

    status, violations = monitor.evaluate_metrics(metrics, monitor.Thresholds())

    assert status == "pass"
    assert violations == []


def test_memory_observability_metrics_fail_on_integrity_drift() -> None:
    metrics = {
        "pending_review": 11,
        "review_required_24h": 6,
        "stale_dream_reviewed_writes": 1,
        "dream_approval_mismatch_count": 1,
        "dream_executed_without_ledger": 1,
    }

    status, violations = monitor.evaluate_metrics(metrics, monitor.Thresholds())

    assert status == "fail"
    keys = {item["key"] for item in violations}
    assert "pending_review" in keys
    assert "stale_dream_reviewed_writes" in keys
    assert "dream_executed_without_ledger" in keys


def test_memory_observability_metrics_warn_on_queue_pressure() -> None:
    thresholds = monitor.Thresholds(max_dream_approved_waiting_execution=2)
    status, violations = monitor.evaluate_metrics(
        {"dream_approved_waiting_execution": 3},
        thresholds,
    )

    assert status == "warn"
    assert violations[0]["severity"] == "warn"


def test_memory_observability_report_suppresses_duplicate_alert() -> None:
    raw = {
        "semantic_metrics": {"pending_review": 99},
        "buddy_metrics": {},
        "proposal_metrics": {},
    }
    report = monitor.build_report(
        raw_metrics=raw,
        thresholds=monitor.Thresholds(),
        dry_run=True,
        no_alert=False,
    )
    raw["recent_alert_fingerprints"] = [report["fingerprint"]]

    duplicate = monitor.build_report(
        raw_metrics=raw,
        thresholds=monitor.Thresholds(),
        dry_run=False,
        no_alert=False,
    )

    assert duplicate["status"] == "fail"
    assert duplicate["duplicate_suppressed"] is True
    assert duplicate["should_alert"] is False


def test_memory_observability_sql_uses_aggregate_metrics_only() -> None:
    sql = monitor.metrics_sql(alert_suppression_hours=6).lower()

    assert "count(*)" in sql
    assert "alpha_semantic_memory" in sql
    assert "alpha_memory_consolidation_proposals" in sql
    assert "q.expires_at <= now()" in sql
    assert "fact" not in sql
    assert "evidence" not in sql


def test_memory_observability_launchagent_template_is_brain_scoped() -> None:
    rendered = PLIST_TEMPLATE.read_text(encoding="utf-8").replace(
        "{{HOME}}",
        "/Users/test",
    )
    parsed = plistlib.loads(rendered.encode("utf-8"))

    assert parsed["Label"] == "com.jarvis.alpha.memory-observability"
    assert parsed["RunAtLoad"] is False
    assert parsed["StartInterval"] == 900
    assert parsed["EnvironmentVariables"]["JARVIS_NODE"] == "brain"
    assert "check_memory_observability.py" in parsed["ProgramArguments"][1]


def test_memory_observability_launchagent_registered_for_brain() -> None:
    from scripts.install_launchagents import SERVICE_NODE_MAP

    assert SERVICE_NODE_MAP["com.jarvis.alpha.memory-observability"] == "brain"


def test_pull_script_refreshes_memory_observability_launchagent() -> None:
    source = PULL_SCRIPT.read_text(encoding="utf-8")

    assert "needs_reload_memory_observability" in source
    assert "check_memory_observability\\.py" in source
    assert "com.jarvis.alpha.memory-observability.plist" in source
    assert 'mark_service_checked "alpha-memory-observability"' in source
