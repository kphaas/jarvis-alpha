from __future__ import annotations

from scripts.check_memory_production_readiness import build_report


def test_build_report_includes_green_production_closeout_evidence() -> None:
    report = build_report(
        db={
            "missing_tables": [],
            "force_rls_missing": [],
            "audit": {
                "approval_audit_rows": 2,
                "graph_audit_rows": 4,
                "graph_open_proposals": 3,
                "graph_stale_proposals": 0,
            },
            "access": {
                "graph_functions_missing": [],
                "graph_public_execute_grants": [],
                "graph_app_execute_missing": [],
                "graph_writer_execute_missing": [],
            },
            "restore": {"restore_drill_events_30d": 1},
        },
        local={
            "backup_script": True,
            "restore_drill_script": True,
            "restore_drill_launchagent": True,
            "observability_monitor": True,
            "memory_core_smoke": True,
        },
    )

    assert report["status"] == "pass"
    assert report["production_ready"] is True
    assert report["production_closeout"]["backup_restore"]["status"] == "pass"
    assert report["production_closeout"]["access_review"]["status"] == "pass"
    assert report["production_closeout"]["audit_log"]["status"] == "pass"
    assert report["production_closeout"]["slo_thresholds"]["status"] == "pass"


def test_build_report_marks_closeout_gaps_actionable() -> None:
    report = build_report(
        db={
            "missing_tables": [],
            "force_rls_missing": ["alpha_memory_graph_nodes"],
            "audit": {
                "approval_audit_rows": 0,
                "graph_audit_rows": 0,
                "graph_open_proposals": 55,
                "graph_stale_proposals": 1,
            },
            "access": {
                "graph_functions_missing": [],
                "graph_public_execute_grants": ["public.memory_graph_health()"],
                "graph_app_execute_missing": [],
                "graph_writer_execute_missing": [],
            },
            "restore": {"restore_drill_events_30d": 0},
        },
        local={
            "backup_script": True,
            "restore_drill_script": True,
            "restore_drill_launchagent": True,
            "observability_monitor": True,
            "memory_core_smoke": True,
        },
    )

    assert report["status"] == "fail"
    assert "force_rls_missing" in report["failures"]
    assert "graph_public_execute_grants" in report["failures"]
    assert report["production_closeout"]["backup_restore"]["status"] == "warn"
    assert report["production_closeout"]["access_review"]["status"] == "fail"
    assert report["production_closeout"]["audit_log"]["status"] == "warn"
    assert report["production_closeout"]["slo_thresholds"]["status"] == "warn"
    assert report["gap_summary"]["p0"] >= 2
