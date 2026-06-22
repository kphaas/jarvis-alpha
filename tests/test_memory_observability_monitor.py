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
        "graph_stale_proposals": 0,
        "graph_approval_mismatch_count": 0,
        "graph_executed_without_audit": 0,
        "graph_open_proposals": 0,
        "dream_reviewed_writes_open": 0,
        "unread_memory_buddy_events": 1,
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
        "graph_stale_proposals": 1,
        "graph_approval_mismatch_count": 1,
        "graph_executed_without_audit": 1,
    }

    status, violations = monitor.evaluate_metrics(metrics, monitor.Thresholds())

    assert status == "fail"
    keys = {item["key"] for item in violations}
    assert "pending_review" in keys
    assert "stale_dream_reviewed_writes" in keys
    assert "dream_executed_without_ledger" in keys
    assert "graph_stale_proposals" in keys
    assert "graph_executed_without_audit" in keys


def test_memory_observability_metrics_warn_on_queue_pressure() -> None:
    thresholds = monitor.Thresholds(max_dream_approved_waiting_execution=2)
    status, violations = monitor.evaluate_metrics(
        {"dream_approved_waiting_execution": 3},
        thresholds,
    )

    assert status == "warn"
    assert violations[0]["severity"] == "warn"


def test_memory_observability_metrics_warn_on_open_graph_writes() -> None:
    thresholds = monitor.Thresholds(max_graph_open_proposals=2)
    status, violations = monitor.evaluate_metrics(
        {"graph_open_proposals": 3},
        thresholds,
    )

    assert status == "warn"
    assert violations[0]["key"] == "graph_open_proposals"


def test_memory_observability_metrics_warn_on_open_writes_and_noise() -> None:
    thresholds = monitor.Thresholds(
        max_dream_reviewed_writes_open=0,
        max_unread_memory_buddy_events=2,
    )
    status, violations = monitor.evaluate_metrics(
        {"dream_reviewed_writes_open": 19, "unread_memory_buddy_events": 3},
        thresholds,
    )

    assert status == "warn"
    assert {item["key"] for item in violations} == {
        "dream_reviewed_writes_open",
        "unread_memory_buddy_events",
    }


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
    assert duplicate["rag"] == "red"
    assert duplicate["overall"] == "blocked"
    assert duplicate["thresholds"]["values"]["max_pending_review"] == 10
    assert duplicate["duplicate_suppressed"] is True
    assert duplicate["should_alert"] is False


def test_memory_observability_report_includes_cleanup_result() -> None:
    report = monitor.build_report(
        raw_metrics={
            "semantic_metrics": {},
            "buddy_metrics": {},
            "proposal_metrics": {},
        },
        thresholds=monitor.Thresholds(),
        dry_run=True,
        no_alert=False,
        cleanup_result={"staled_proposals": 2, "released_holds": 1},
    )

    assert report["status"] == "pass"
    assert report["cleanup"] == {"staled_proposals": 2, "released_holds": 1}


def test_memory_observability_cleanup_runs_before_metric_fetch(
    monkeypatch,
    capsys,
) -> None:
    calls: list[str] = []

    monkeypatch.setattr("sys.argv", ["check_memory_observability.py"])
    monkeypatch.setattr(monitor, "default_secrets_file", lambda: Path("/missing"))
    monkeypatch.setattr(monitor, "load_secret_env", lambda _path: {})
    monkeypatch.setattr(
        monitor, "thresholds_from_env", lambda _env: monitor.Thresholds()
    )

    def fake_cleanup(_env):
        calls.append("cleanup")
        return {"staled_proposals": 1}

    def fake_fetch(_env, _thresholds):
        calls.append("fetch")
        return {
            "semantic_metrics": {},
            "buddy_metrics": {},
            "proposal_metrics": {},
        }

    monkeypatch.setattr(
        monitor, "cleanup_stale_memory_consolidation_proposals", fake_cleanup
    )
    monkeypatch.setattr(monitor, "fetch_metrics", fake_fetch)

    assert monitor.main() == 0
    assert calls == ["cleanup", "fetch"]
    payload = capsys.readouterr().out
    assert '"staled_proposals": 1' in payload


def test_memory_observability_sql_uses_aggregate_metrics_only() -> None:
    sql = monitor.metrics_sql(alert_suppression_hours=6).lower()

    assert "count(*)" in sql
    assert "alpha_semantic_memory" in sql
    assert "alpha_memory_consolidation_proposals" in sql
    assert "alpha_memory_graph_proposals" in sql
    assert "alpha_memory_graph_audit" in sql
    assert "q.expires_at <= now()" in sql
    assert "actionable_unread" in sql
    assert "payload ? 'memory_suppression'" in sql
    assert "priority >= 3 and title ilike '%memory%'" in sql
    assert "fact" not in sql
    assert "evidence" not in sql


def test_memory_observability_cleanup_sql_calls_secdef_function() -> None:
    sql = monitor.cleanup_sql().lower()

    assert "expire_stale_memory_consolidation_proposals" in sql
    assert "expire_stale_memory_graph_proposals" in sql
    assert "jsonb_build_object" in sql
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
