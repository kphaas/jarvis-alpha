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
    assert "alpha_memory_graph_nodes" in sql
    assert "alpha_memory_graph_edges" in sql
    assert "alpha_memory_graph_proposals" in sql
    assert "alpha_memory_graph_audit" in sql
    assert "alpha_approval_audit" in sql
    assert "relrowsecurity" in sql
    assert "relforcerowsecurity" in sql
    assert "restore drill" in sql
    assert "graph_functions" in sql
    assert "graph_public_execute_grants" in sql
    assert "graph_open_proposals" in sql
    assert "graph_stale_proposals" in sql
    assert "expire_stale_memory_graph_proposals" in sql
    assert "has_function_privilege('public'" in sql
    assert "aclexplode" not in sql
    assert "fact" not in sql
    assert "evidence" not in sql


def test_memory_readiness_report_rag_states() -> None:
    passing = readiness.build_report(
        db={
            "missing_tables": [],
            "force_rls_missing": [],
            "audit": {
                "approval_audit_rows": 3,
                "graph_audit_rows": 1,
                "graph_open_proposals": 1,
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
            "memory_graph_smoke": True,
        },
    )
    warning = readiness.build_report(
        db={
            "missing_tables": [],
            "force_rls_missing": [],
            "audit": {
                "approval_audit_rows": 0,
                "graph_audit_rows": 0,
                "graph_open_proposals": 1,
                "graph_stale_proposals": 0,
            },
            "access": {
                "graph_functions_missing": [],
                "graph_public_execute_grants": [],
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
            "memory_graph_smoke": True,
        },
    )
    failing = readiness.build_report(
        db={
            "missing_tables": ["alpha_semantic_memory"],
            "force_rls_missing": [],
            "audit": {
                "approval_audit_rows": 3,
                "graph_audit_rows": 1,
                "graph_open_proposals": 1,
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
            "memory_graph_smoke": True,
        },
    )

    assert passing["rag"] == "green"
    assert passing["production_ready"] is True
    assert passing["next_actions"] == []
    assert passing["gap_summary"] == {"p0": 0, "p1": 0, "p2": 0}
    assert warning["rag"] == "yellow"
    assert warning["production_ready"] is False
    assert "graph_audit_empty" in warning["warnings"]
    assert "restore_drill_not_observed_30d" in warning["warnings"]
    assert warning["gap_summary"] == {"p0": 0, "p1": 3, "p2": 0}
    assert [action["gap"] for action in warning["next_actions"]] == [
        "graph_audit_empty",
        "approval_audit_empty",
        "restore_drill_not_observed_30d",
    ]
    assert failing["rag"] == "red"
    assert failing["production_ready"] is False
    assert "missing_tables" in failing["failures"]
    assert failing["gap_summary"] == {"p0": 1, "p1": 0, "p2": 0}
    assert failing["next_actions"][0] == {
        "priority": "P0",
        "gap": "missing_memory_tables",
        "item": "Apply or repair memory schema migrations",
        "detail": "alpha_semantic_memory",
        "owner": "Ken",
        "target_date": "TBD",
    }


def test_memory_readiness_blocks_graph_access_drift() -> None:
    report = readiness.build_report(
        db={
            "missing_tables": [],
            "force_rls_missing": [],
            "audit": {
                "approval_audit_rows": 3,
                "graph_audit_rows": 1,
                "graph_open_proposals": 1,
                "graph_stale_proposals": 0,
            },
            "access": {
                "graph_functions_missing": [
                    "public.memory_graph_health()",
                ],
                "graph_public_execute_grants": [
                    "public.execute_memory_graph_proposal(uuid,uuid,text)",
                ],
                "graph_app_execute_missing": [],
                "graph_writer_execute_missing": [
                    "public.propose_memory_graph_write(uuid,text,text,jsonb,text,text,text)",
                ],
            },
            "restore": {"restore_drill_events_30d": 1},
        },
        local={
            "backup_script": True,
            "restore_drill_script": True,
            "restore_drill_launchagent": True,
            "observability_monitor": True,
            "memory_core_smoke": True,
            "memory_graph_smoke": True,
        },
    )

    assert report["rag"] == "red"
    assert report["production_ready"] is False
    assert report["gap_summary"] == {"p0": 3, "p1": 0, "p2": 0}
    assert [action["gap"] for action in report["next_actions"]] == [
        "graph_functions_missing",
        "graph_public_execute_grants",
        "graph_function_execute_grants_missing",
    ]


def test_memory_readiness_runtime_counts_skip_missing_tables(
    monkeypatch,
) -> None:
    calls: list[str] = []

    def fake_run_psql_json(sql: str, env: dict[str, str]) -> dict:
        calls.append(sql)
        return {"unexpected": True}

    monkeypatch.setattr(readiness, "run_psql_json", fake_run_psql_json)

    runtime = readiness.runtime_readiness_counts(
        {
            "missing_tables": [
                "alpha_approval_audit",
                "alpha_memory_graph_audit",
                "alpha_buddy_events",
            ],
        },
        {},
    )

    assert runtime == {}
    assert calls == []


def test_memory_readiness_local_files_check(tmp_path: Path) -> None:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "launchagents").mkdir()
    (tmp_path / "scripts" / "pg_backup_alpha.sh").touch()
    (tmp_path / "scripts" / "restore_drill_alpha.sh").touch()
    (tmp_path / "scripts" / "check_memory_observability.py").touch()
    (tmp_path / "scripts" / "smoke_memory_core.py").touch()
    (tmp_path / "scripts" / "smoke_memory_graph.py").touch()
    (
        tmp_path / "launchagents" / "com.jarvis.alpha.restore_drill.template.plist"
    ).touch()

    assert all(readiness.local_readiness(tmp_path).values())
