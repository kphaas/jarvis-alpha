from __future__ import annotations

from pathlib import Path

from scripts import check_memory_production_readiness as readiness


def test_memory_readiness_sql_checks_tables_rls_restore_and_audit() -> None:
    sql = readiness.readiness_sql().lower()

    assert "alpha_semantic_memory" in sql
    assert "alpha_conversation_memory" in sql
    assert "alpha_buddy_events" in sql
    assert "alpha_buddy_events_archive" in sql
    assert "alpha_memory_consolidation_proposals" in sql
    assert "alpha_memory_consolidation_execution_ledger" in sql
    assert "alpha_approval_audit" in sql
    assert "relrowsecurity" in sql
    assert "relforcerowsecurity" in sql
    assert "restore drill" in sql
    assert "fact" not in sql
    assert "evidence" not in sql


def test_memory_readiness_report_rag_states() -> None:
    passing = readiness.build_report(
        db={
            "missing_tables": [],
            "force_rls_missing": [],
            "audit": {"approval_audit_rows": 3},
            "restore": {"restore_drill_events_30d": 1},
        },
        local={
            "backup_script": True,
            "restore_drill_script": True,
            "restore_drill_launchagent": True,
            "observability_monitor": True,
        },
    )
    warning = readiness.build_report(
        db={
            "missing_tables": [],
            "force_rls_missing": [],
            "audit": {"approval_audit_rows": 0},
            "restore": {"restore_drill_events_30d": 0},
        },
        local={
            "backup_script": True,
            "restore_drill_script": True,
            "restore_drill_launchagent": True,
            "observability_monitor": True,
        },
    )
    failing = readiness.build_report(
        db={
            "missing_tables": ["alpha_semantic_memory"],
            "force_rls_missing": [],
            "audit": {"approval_audit_rows": 3},
            "restore": {"restore_drill_events_30d": 1},
        },
        local={
            "backup_script": True,
            "restore_drill_script": True,
            "restore_drill_launchagent": True,
            "observability_monitor": True,
        },
    )

    assert passing["rag"] == "green"
    assert warning["rag"] == "yellow"
    assert "restore_drill_not_observed_30d" in warning["warnings"]
    assert failing["rag"] == "red"
    assert "missing_tables" in failing["failures"]


def test_memory_readiness_local_files_check(tmp_path: Path) -> None:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "launchagents").mkdir()
    (tmp_path / "scripts" / "pg_backup_alpha.sh").touch()
    (tmp_path / "scripts" / "restore_drill_alpha.sh").touch()
    (tmp_path / "scripts" / "check_memory_observability.py").touch()
    (
        tmp_path / "launchagents" / "com.jarvis.alpha.restore_drill.template.plist"
    ).touch()

    assert all(readiness.local_readiness(tmp_path).values())
