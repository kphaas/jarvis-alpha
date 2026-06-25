#!/usr/bin/env python3
"""Read-only production readiness checks for Alpha memory operations.

This script emits aggregate metadata only. It must not select memory facts,
proposal evidence, message bodies, or other user-visible content.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.check_memory_observability import (  # noqa: E402
    default_secrets_file,
    load_secret_env,
    run_psql_json,
)


REQUIRED_MEMORY_TABLES = (
    "alpha_semantic_memory",
    "alpha_conversation_memory",
    "alpha_buddy_events",
    "alpha_buddy_events_archive",
    "alpha_memory_consolidation_proposals",
    "alpha_memory_consolidation_execution_ledger",
    "alpha_memory_graph_nodes",
    "alpha_memory_graph_edges",
    "alpha_memory_graph_proposals",
    "alpha_memory_graph_audit",
    "alpha_approval_queue",
    "alpha_approval_audit",
)

REQUIRED_FORCE_RLS_TABLES = (
    "alpha_semantic_memory",
    "alpha_conversation_memory",
    "alpha_buddy_events",
    "alpha_buddy_events_archive",
    "alpha_memory_consolidation_proposals",
    "alpha_memory_consolidation_execution_ledger",
    "alpha_memory_graph_nodes",
    "alpha_memory_graph_edges",
    "alpha_memory_graph_proposals",
    "alpha_memory_graph_audit",
    "alpha_approval_queue",
    "alpha_approval_audit",
)


def readiness_sql() -> str:
    required_tables = ", ".join(f"('{name}')" for name in REQUIRED_MEMORY_TABLES)
    force_tables = ", ".join(f"('{name}')" for name in REQUIRED_FORCE_RLS_TABLES)
    return f"""
-- Runtime audit and restore drill counts are queried separately after table
-- presence is known, so missing required tables produce a red report instead
-- of a relation-not-found crash.
WITH required_tables(name) AS (
    VALUES {required_tables}
),
required_force_rls(name) AS (
    VALUES {force_tables}
),
graph_functions(signature, requires_app_writer) AS (
    VALUES
        ('public.propose_memory_graph_write(uuid,text,text,jsonb,text,text,text)', true),
        ('public.execute_memory_graph_proposal(uuid,uuid,text)', true),
        ('public.list_memory_graph_current(uuid,timestamp with time zone,integer)', true),
        ('public.list_memory_graph_history(uuid,uuid,integer)', true),
        ('public.list_memory_graph_proposals(uuid,text,integer)', true),
        ('public.expire_stale_memory_graph_proposals()', true),
        ('public.memory_graph_health()', true),
        ('public.enforce_memory_graph_valid_window()', false)
),
graph_function_oids AS (
    SELECT
        signature,
        requires_app_writer,
        to_regprocedure(signature) AS func_oid
    FROM graph_functions
),
table_status AS (
    SELECT
        r.name,
        to_regclass('public.' || r.name) IS NOT NULL AS present
    FROM required_tables r
),
force_rls_status AS (
    SELECT
        r.name,
        COALESCE(c.relrowsecurity AND c.relforcerowsecurity, false) AS force_rls
    FROM required_force_rls r
    LEFT JOIN pg_class c
      ON c.relname = r.name
     AND c.relnamespace = 'public'::regnamespace
),
graph_function_status AS (
    SELECT
        f.signature,
        f.func_oid,
        f.requires_app_writer,
        f.func_oid IS NOT NULL AS present,
        CASE
            WHEN f.func_oid IS NULL THEN false
            ELSE has_function_privilege('public', f.func_oid, 'EXECUTE')
        END AS public_execute,
        CASE
            WHEN NOT f.requires_app_writer THEN true
            WHEN to_regrole('jarvis_alpha_app') IS NULL
              OR f.func_oid IS NULL THEN false
            ELSE has_function_privilege('jarvis_alpha_app', f.func_oid, 'EXECUTE')
        END AS app_execute,
        CASE
            WHEN NOT f.requires_app_writer THEN true
            WHEN to_regrole('jarvis_alpha_writer') IS NULL
              OR f.func_oid IS NULL THEN false
            ELSE has_function_privilege('jarvis_alpha_writer', f.func_oid, 'EXECUTE')
        END AS writer_execute
    FROM graph_function_oids f
)
SELECT jsonb_build_object(
    'required_tables', (
        SELECT jsonb_object_agg(name, present ORDER BY name)
        FROM table_status
    ),
    'missing_tables', COALESCE((
        SELECT jsonb_agg(name ORDER BY name)
        FROM table_status
        WHERE NOT present
    ), '[]'::jsonb),
    'force_rls', (
        SELECT jsonb_object_agg(name, force_rls ORDER BY name)
        FROM force_rls_status
    ),
    'force_rls_missing', COALESCE((
        SELECT jsonb_agg(name ORDER BY name)
        FROM force_rls_status
        WHERE NOT force_rls
    ), '[]'::jsonb),
    'audit', jsonb_build_object(
        'approval_audit_rows', 0,
        'consolidation_ledger_rows', 0,
        'graph_audit_rows', 0,
        'graph_open_proposals', 0,
        'graph_stale_proposals', 0,
        'active_approval_rows', 0
    ),
    'access', jsonb_build_object(
        'graph_functions_missing', COALESCE((
            SELECT jsonb_agg(signature ORDER BY signature)
            FROM graph_function_status
            WHERE NOT present
        ), '[]'::jsonb),
        'graph_public_execute_grants', COALESCE((
            SELECT jsonb_agg(signature ORDER BY signature)
            FROM graph_function_status
            WHERE public_execute
        ), '[]'::jsonb),
        'graph_app_execute_missing', COALESCE((
            SELECT jsonb_agg(signature ORDER BY signature)
            FROM graph_function_status
            WHERE NOT app_execute
        ), '[]'::jsonb),
        'graph_writer_execute_missing', COALESCE((
            SELECT jsonb_agg(signature ORDER BY signature)
            FROM graph_function_status
            WHERE NOT writer_execute
        ), '[]'::jsonb)
    ),
    'restore', jsonb_build_object('restore_drill_events_30d', 0)
)::text
;
"""


def audit_sql() -> str:
    return """
SELECT jsonb_build_object(
    'approval_audit_rows',
        (SELECT COUNT(*)::int FROM public.alpha_approval_audit),
    'consolidation_ledger_rows',
        (SELECT COUNT(*)::int
           FROM public.alpha_memory_consolidation_execution_ledger),
    'graph_audit_rows',
        (SELECT COUNT(*)::int
           FROM public.alpha_memory_graph_audit),
    'graph_open_proposals',
        (SELECT COUNT(*)::int
           FROM public.alpha_memory_graph_proposals
          WHERE status IN ('pending_review', 'queued', 'approved')),
    'graph_stale_proposals',
        (SELECT COUNT(*)::int
           FROM public.alpha_memory_graph_proposals
          WHERE status = 'stale'),
    'active_approval_rows',
        (SELECT COUNT(*)::int
           FROM public.alpha_approval_queue
          WHERE status IN ('pending', 'approved')
            AND expires_at > now())
)::text;
"""


def restore_sql() -> str:
    return """
SELECT jsonb_build_object(
    'restore_drill_events_30d',
        COUNT(*)::int
)::text
FROM public.alpha_buddy_events
WHERE created_at >= now() - INTERVAL '30 days'
  AND (
    source = 'restore_drill_alpha'
    OR title ILIKE 'Restore drill%'
  );
"""


def local_readiness(repo_root: Path) -> dict[str, bool]:
    paths = {
        "backup_script": repo_root / "scripts" / "pg_backup_alpha.sh",
        "restore_drill_script": repo_root / "scripts" / "restore_drill_alpha.sh",
        "restore_drill_launchagent": repo_root
        / "launchagents"
        / "com.jarvis.alpha.restore_drill.template.plist",
        "observability_monitor": repo_root
        / "scripts"
        / "check_memory_observability.py",
        "memory_core_smoke": repo_root / "scripts" / "smoke_memory_core.py",
        "memory_graph_smoke": repo_root / "scripts" / "smoke_memory_graph.py",
    }
    return {name: path.is_file() for name, path in paths.items()}


def build_report(
    *,
    db: dict[str, Any],
    local: dict[str, bool],
) -> dict[str, Any]:
    missing_tables = _list(db.get("missing_tables"))
    force_rls_missing = _list(db.get("force_rls_missing"))
    audit = db.get("audit") if isinstance(db.get("audit"), dict) else {}
    access = db.get("access") if isinstance(db.get("access"), dict) else {}
    restore = db.get("restore") if isinstance(db.get("restore"), dict) else {}
    local_missing = sorted(name for name, present in local.items() if not present)
    graph_functions_missing = _list(access.get("graph_functions_missing"))
    graph_public_execute_grants = _list(access.get("graph_public_execute_grants"))
    graph_app_execute_missing = _list(access.get("graph_app_execute_missing"))
    graph_writer_execute_missing = _list(access.get("graph_writer_execute_missing"))
    warnings: list[str] = []
    failures: list[str] = []
    if missing_tables:
        failures.append("missing_tables")
    if force_rls_missing:
        failures.append("force_rls_missing")
    if graph_functions_missing:
        failures.append("graph_functions_missing")
    if graph_public_execute_grants:
        failures.append("graph_public_execute_grants")
    if graph_app_execute_missing or graph_writer_execute_missing:
        failures.append("graph_function_execute_grants_missing")
    if local_missing:
        failures.append("local_readiness_files_missing")
    if int(audit.get("approval_audit_rows") or 0) < 1:
        warnings.append("approval_audit_empty")
    if int(audit.get("graph_audit_rows") or 0) < 1:
        warnings.append("graph_audit_empty")
    if int(audit.get("graph_stale_proposals") or 0) > 0:
        warnings.append("graph_stale_proposals_present")
    if int(audit.get("graph_open_proposals") or 0) > 50:
        warnings.append("graph_open_proposal_pressure")
    if int(restore.get("restore_drill_events_30d") or 0) < 1:
        warnings.append("restore_drill_not_observed_30d")
    next_actions = build_next_actions(
        missing_tables=missing_tables,
        force_rls_missing=force_rls_missing,
        local_missing=local_missing,
        warnings=warnings,
        graph_functions_missing=graph_functions_missing,
        graph_public_execute_grants=graph_public_execute_grants,
        graph_execute_missing=sorted(
            set(graph_app_execute_missing + graph_writer_execute_missing)
        ),
    )
    production_closeout = build_production_closeout(
        db=db,
        local=local,
        missing_tables=missing_tables,
        force_rls_missing=force_rls_missing,
        graph_functions_missing=graph_functions_missing,
        graph_public_execute_grants=graph_public_execute_grants,
        graph_execute_missing=sorted(
            set(graph_app_execute_missing + graph_writer_execute_missing)
        ),
    )

    if failures:
        status = "fail"
        rag = "red"
        icon = "🔴"
        overall = "blocked"
    elif warnings:
        status = "warn"
        rag = "yellow"
        icon = "🟡"
        overall = "at_risk"
    else:
        status = "pass"
        rag = "green"
        icon = "🟢"
        overall = "on_track"

    return {
        "status": status,
        "rag": rag,
        "rag_icon": icon,
        "overall": overall,
        "checked_at": datetime.now(UTC).isoformat(),
        "checks": {
            "missing_tables": missing_tables,
            "force_rls_missing": force_rls_missing,
            "local_missing": local_missing,
            "audit": audit,
            "access": access,
            "restore": restore,
            "local": local,
        },
        "warnings": warnings,
        "failures": failures,
        "production_closeout": production_closeout,
        "production_ready": not failures and not warnings,
        "next_actions": next_actions,
        "gap_summary": {
            "p0": sum(1 for action in next_actions if action["priority"] == "P0"),
            "p1": sum(1 for action in next_actions if action["priority"] == "P1"),
            "p2": sum(1 for action in next_actions if action["priority"] == "P2"),
        },
    }


def build_production_closeout(
    *,
    db: dict[str, Any],
    local: dict[str, bool],
    missing_tables: list[str] | None = None,
    force_rls_missing: list[str] | None = None,
    graph_functions_missing: list[str] | None = None,
    graph_public_execute_grants: list[str] | None = None,
    graph_execute_missing: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    audit = db.get("audit") if isinstance(db.get("audit"), dict) else {}
    restore = db.get("restore") if isinstance(db.get("restore"), dict) else {}
    missing_tables = missing_tables or _list(db.get("missing_tables"))
    force_rls_missing = force_rls_missing or _list(db.get("force_rls_missing"))
    access = db.get("access") if isinstance(db.get("access"), dict) else {}
    graph_functions_missing = graph_functions_missing or _list(
        access.get("graph_functions_missing")
    )
    graph_public_execute_grants = graph_public_execute_grants or _list(
        access.get("graph_public_execute_grants")
    )
    graph_execute_missing = graph_execute_missing or sorted(
        set(
            _list(access.get("graph_app_execute_missing"))
            + _list(access.get("graph_writer_execute_missing"))
        )
    )

    backup_files_ok = bool(local.get("backup_script")) and bool(
        local.get("restore_drill_script")
    )
    restore_events = int(restore.get("restore_drill_events_30d") or 0)
    graph_open = int(audit.get("graph_open_proposals") or 0)
    graph_stale = int(audit.get("graph_stale_proposals") or 0)
    approval_audit_rows = int(audit.get("approval_audit_rows") or 0)
    graph_audit_rows = int(audit.get("graph_audit_rows") or 0)

    return {
        "backup_restore": _closeout_item(
            status="pass" if backup_files_ok and restore_events >= 1 else "warn",
            evidence={
                "backup_script": bool(local.get("backup_script")),
                "restore_drill_script": bool(local.get("restore_drill_script")),
                "restore_drill_events_30d": restore_events,
            },
            required="backup script, restore drill script, and one restore drill event in 30d",
        ),
        "access_review": _closeout_item(
            status=(
                "pass"
                if not (
                    missing_tables
                    or force_rls_missing
                    or graph_functions_missing
                    or graph_public_execute_grants
                    or graph_execute_missing
                )
                else "fail"
            ),
            evidence={
                "missing_tables": missing_tables,
                "force_rls_missing": force_rls_missing,
                "graph_functions_missing": graph_functions_missing,
                "graph_public_execute_grants": graph_public_execute_grants,
                "graph_execute_missing": graph_execute_missing,
            },
            required="all required tables present, FORCE RLS enabled, app/writer grants present, public EXECUTE absent",
        ),
        "audit_log": _closeout_item(
            status="pass"
            if approval_audit_rows >= 1 and graph_audit_rows >= 1
            else "warn",
            evidence={
                "approval_audit_rows": approval_audit_rows,
                "graph_audit_rows": graph_audit_rows,
            },
            required="approval and graph audit rows observed",
        ),
        "slo_thresholds": _closeout_item(
            status="pass" if graph_stale == 0 and graph_open <= 50 else "warn",
            evidence={
                "graph_open_proposals": graph_open,
                "graph_stale_proposals": graph_stale,
                "max_graph_open_proposals": 50,
                "max_graph_stale_proposals": 0,
            },
            required="no stale graph proposals and reviewed-write queue at or below SLO",
        ),
    }


def _closeout_item(
    *,
    status: str,
    evidence: dict[str, Any],
    required: str,
) -> dict[str, Any]:
    return {
        "status": status,
        "evidence": evidence,
        "required": required,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check Alpha memory production readiness metadata",
    )
    parser.add_argument(
        "--secrets-file",
        type=Path,
        default=None,
        help="Override secrets file path",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    secrets_file = args.secrets_file or default_secrets_file()
    env = os.environ.copy()
    env.update(load_secret_env(secrets_file))
    env.setdefault("PGHOST", "127.0.0.1")
    env.setdefault("PGUSER", "jarvisbrain")
    env.setdefault("PGDATABASE", "jarvis_alpha")
    if "POSTGRES_PASSWORD" in env and "PGPASSWORD" not in env:
        env["PGPASSWORD"] = env["POSTGRES_PASSWORD"]

    try:
        raw_db = run_psql_json(readiness_sql(), env)
        db = raw_db if isinstance(raw_db, dict) else {}
        db.update(runtime_readiness_counts(db, env))
        report = build_report(db=db, local=local_readiness(REPO_ROOT))
        print(json.dumps(report, sort_keys=True))
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "rag": "red",
                    "rag_icon": "🔴",
                    "overall": "blocked",
                    "error": str(exc),
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    if report["status"] == "fail":
        return 2
    return 0


def _list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item]


def build_next_actions(
    *,
    missing_tables: list[str],
    force_rls_missing: list[str],
    local_missing: list[str],
    warnings: list[str],
    graph_functions_missing: list[str] | None = None,
    graph_public_execute_grants: list[str] | None = None,
    graph_execute_missing: list[str] | None = None,
) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []
    if missing_tables:
        actions.append(
            _action(
                priority="P0",
                gap="missing_memory_tables",
                item="Apply or repair memory schema migrations",
                detail=", ".join(missing_tables),
            )
        )
    if force_rls_missing:
        actions.append(
            _action(
                priority="P0",
                gap="force_rls_missing",
                item="Enable FORCE RLS on memory governance tables",
                detail=", ".join(force_rls_missing),
            )
        )
    if local_missing:
        actions.append(
            _action(
                priority="P1",
                gap="local_readiness_files_missing",
                item="Install missing backup, restore, or monitor files",
                detail=", ".join(local_missing),
            )
        )
    if graph_functions_missing:
        actions.append(
            _action(
                priority="P0",
                gap="graph_functions_missing",
                item="Apply or repair temporal graph SECDEF functions",
                detail=", ".join(graph_functions_missing),
            )
        )
    if graph_public_execute_grants:
        actions.append(
            _action(
                priority="P0",
                gap="graph_public_execute_grants",
                item="Revoke public EXECUTE on temporal graph functions",
                detail=", ".join(graph_public_execute_grants),
            )
        )
    if graph_execute_missing:
        actions.append(
            _action(
                priority="P0",
                gap="graph_function_execute_grants_missing",
                item="Grant app/writer EXECUTE on temporal graph functions",
                detail=", ".join(graph_execute_missing),
            )
        )
    if "graph_audit_empty" in warnings:
        actions.append(
            _action(
                priority="P1",
                gap="graph_audit_empty",
                item="Run graph proposal execute smoke and confirm audit rows",
                detail="graph_audit_rows=0",
            )
        )
    if "graph_stale_proposals_present" in warnings:
        actions.append(
            _action(
                priority="P1",
                gap="graph_stale_proposals_present",
                item="Review or archive stale temporal graph proposals",
                detail="graph_stale_proposals>0",
            )
        )
    if "graph_open_proposal_pressure" in warnings:
        actions.append(
            _action(
                priority="P1",
                gap="graph_open_proposal_pressure",
                item="Drain temporal graph reviewed-write queue",
                detail="graph_open_proposals>50",
            )
        )
    if "approval_audit_empty" in warnings:
        actions.append(
            _action(
                priority="P1",
                gap="approval_audit_empty",
                item="Run an approval-path smoke and confirm audit rows",
                detail="approval_audit_rows=0",
            )
        )
    if "restore_drill_not_observed_30d" in warnings:
        actions.append(
            _action(
                priority="P1",
                gap="restore_drill_not_observed_30d",
                item="Run the Alpha memory restore drill and confirm Buddy event",
                detail="restore_drill_events_30d=0",
            )
        )
    return actions


def _action(
    *,
    priority: str,
    gap: str,
    item: str,
    detail: str,
) -> dict[str, str]:
    return {
        "priority": priority,
        "gap": gap,
        "item": item,
        "detail": detail,
        "owner": "Ken",
        "target_date": "TBD",
    }


def runtime_readiness_counts(
    db: dict[str, Any],
    env: dict[str, str],
) -> dict[str, dict[str, Any]]:
    missing_tables = set(_list(db.get("missing_tables")))
    runtime: dict[str, dict[str, Any]] = {}
    audit_tables = {
        "alpha_approval_audit",
        "alpha_memory_consolidation_execution_ledger",
        "alpha_memory_graph_audit",
        "alpha_approval_queue",
    }
    if not audit_tables.intersection(missing_tables):
        raw_audit = run_psql_json(audit_sql(), env)
        if isinstance(raw_audit, dict):
            runtime["audit"] = raw_audit
    if "alpha_buddy_events" not in missing_tables:
        raw_restore = run_psql_json(restore_sql(), env)
        if isinstance(raw_restore, dict):
            runtime["restore"] = raw_restore
    return runtime


if __name__ == "__main__":
    raise SystemExit(main())
