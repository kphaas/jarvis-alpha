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
        'active_approval_rows', 0
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
    restore = db.get("restore") if isinstance(db.get("restore"), dict) else {}
    local_missing = sorted(name for name, present in local.items() if not present)
    warnings: list[str] = []
    failures: list[str] = []
    if missing_tables:
        failures.append("missing_tables")
    if force_rls_missing:
        failures.append("force_rls_missing")
    if local_missing:
        failures.append("local_readiness_files_missing")
    if int(audit.get("approval_audit_rows") or 0) < 1:
        warnings.append("approval_audit_empty")
    if int(restore.get("restore_drill_events_30d") or 0) < 1:
        warnings.append("restore_drill_not_observed_30d")
    next_actions = build_next_actions(
        missing_tables=missing_tables,
        force_rls_missing=force_rls_missing,
        local_missing=local_missing,
        warnings=warnings,
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
            "restore": restore,
            "local": local,
        },
        "warnings": warnings,
        "failures": failures,
        "production_ready": not failures and not warnings,
        "next_actions": next_actions,
        "gap_summary": {
            "p0": sum(1 for action in next_actions if action["priority"] == "P0"),
            "p1": sum(1 for action in next_actions if action["priority"] == "P1"),
            "p2": sum(1 for action in next_actions if action["priority"] == "P2"),
        },
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
