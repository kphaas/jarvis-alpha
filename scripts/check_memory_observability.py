#!/usr/bin/env python3
"""Evaluate memory/Dream production SLOs and optionally raise a Buddy event.

The monitor emits aggregate counts only. It must never log memory facts,
proposal evidence, or user-visible raw text.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


MONITOR_SOURCE = "memory_observability_monitor"


@dataclass(frozen=True)
class Thresholds:
    max_pending_review: int = 10
    max_review_required_24h: int = 5
    max_dream_reviewed_writes_open: int = 0
    max_stale_dream_reviewed_writes: int = 0
    max_dream_approval_mismatch_count: int = 0
    max_dream_executed_without_ledger: int = 0
    max_unread_memory_buddy_events: int = 500
    max_high_priority_unread: int = 10
    max_dream_approved_waiting_execution: int = 100
    alert_suppression_hours: int = 6


def _env_int(env: dict[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc


def thresholds_from_env(env: dict[str, str] | None = None) -> Thresholds:
    source = env or os.environ
    defaults = Thresholds()
    return Thresholds(
        max_pending_review=_env_int(
            source,
            "MEMORY_OBS_MAX_PENDING_REVIEW",
            defaults.max_pending_review,
        ),
        max_review_required_24h=_env_int(
            source,
            "MEMORY_OBS_MAX_REVIEW_REQUIRED_24H",
            defaults.max_review_required_24h,
        ),
        max_dream_reviewed_writes_open=_env_int(
            source,
            "MEMORY_OBS_MAX_DREAM_REVIEWED_WRITES_OPEN",
            defaults.max_dream_reviewed_writes_open,
        ),
        max_stale_dream_reviewed_writes=_env_int(
            source,
            "MEMORY_OBS_MAX_STALE_DREAM_REVIEWED_WRITES",
            defaults.max_stale_dream_reviewed_writes,
        ),
        max_dream_approval_mismatch_count=_env_int(
            source,
            "MEMORY_OBS_MAX_DREAM_APPROVAL_MISMATCH_COUNT",
            defaults.max_dream_approval_mismatch_count,
        ),
        max_dream_executed_without_ledger=_env_int(
            source,
            "MEMORY_OBS_MAX_DREAM_EXECUTED_WITHOUT_LEDGER",
            defaults.max_dream_executed_without_ledger,
        ),
        max_unread_memory_buddy_events=_env_int(
            source,
            "MEMORY_OBS_MAX_UNREAD_MEMORY_BUDDY_EVENTS",
            defaults.max_unread_memory_buddy_events,
        ),
        max_high_priority_unread=_env_int(
            source,
            "MEMORY_OBS_MAX_HIGH_PRIORITY_UNREAD",
            defaults.max_high_priority_unread,
        ),
        max_dream_approved_waiting_execution=_env_int(
            source,
            "MEMORY_OBS_MAX_DREAM_APPROVED_WAITING_EXECUTION",
            defaults.max_dream_approved_waiting_execution,
        ),
        alert_suppression_hours=_env_int(
            source,
            "MEMORY_OBS_ALERT_SUPPRESSION_HOURS",
            defaults.alert_suppression_hours,
        ),
    )


def flatten_metrics(raw: dict[str, Any]) -> dict[str, int]:
    metrics: dict[str, int] = {}
    for section in (
        "semantic_metrics",
        "buddy_metrics",
        "proposal_metrics",
    ):
        values = raw.get(section) or {}
        if not isinstance(values, dict):
            continue
        for key, value in values.items():
            if isinstance(value, bool):
                metrics[key] = int(value)
            elif isinstance(value, int):
                metrics[key] = value
            elif value is None:
                metrics[key] = 0
            else:
                try:
                    metrics[key] = int(value)
                except (TypeError, ValueError):
                    metrics[key] = 0
    return metrics


def _violation(
    *,
    key: str,
    severity: str,
    value: int,
    threshold: int,
    description: str,
) -> dict[str, object]:
    return {
        "key": key,
        "severity": severity,
        "value": value,
        "threshold": threshold,
        "description": description,
    }


def evaluate_metrics(
    metrics: dict[str, int],
    thresholds: Thresholds,
) -> tuple[str, list[dict[str, object]]]:
    violations: list[dict[str, object]] = []

    checks = [
        (
            "pending_review",
            thresholds.max_pending_review,
            "fail",
            "semantic review backlog above SLO",
        ),
        (
            "review_required_24h",
            thresholds.max_review_required_24h,
            "fail",
            "new high-visibility review writes above daily SLO",
        ),
        (
            "stale_dream_reviewed_writes",
            thresholds.max_stale_dream_reviewed_writes,
            "fail",
            "Dream reviewed writes stale longer than 48 hours",
        ),
        (
            "dream_approval_mismatch_count",
            thresholds.max_dream_approval_mismatch_count,
            "fail",
            "Dream proposal approval queue drift detected",
        ),
        (
            "dream_executed_without_ledger",
            thresholds.max_dream_executed_without_ledger,
            "fail",
            "Dream proposal executed without execution ledger row",
        ),
        (
            "dream_reviewed_writes_open",
            thresholds.max_dream_reviewed_writes_open,
            "warn",
            "Dream reviewed writes are waiting for operator action",
        ),
        (
            "unread_memory_buddy_events",
            thresholds.max_unread_memory_buddy_events,
            "warn",
            "unread memory Buddy events above operator-noise SLO",
        ),
        (
            "high_priority_buddy_events",
            thresholds.max_high_priority_unread,
            "warn",
            "high-priority memory Buddy events above review SLO",
        ),
        (
            "dream_approved_waiting_execution",
            thresholds.max_dream_approved_waiting_execution,
            "warn",
            "approved Dream writes waiting for execution above queue SLO",
        ),
    ]
    for key, threshold, severity, description in checks:
        value = metrics.get(key, 0)
        if value > threshold:
            violations.append(
                _violation(
                    key=key,
                    severity=severity,
                    value=value,
                    threshold=threshold,
                    description=description,
                )
            )

    if any(item["severity"] == "fail" for item in violations):
        return "fail", violations
    if violations:
        return "warn", violations
    return "pass", []


def rag_for_status(status: str) -> tuple[str, str, str]:
    if status == "fail":
        return "red", "🔴", "blocked"
    if status == "warn":
        return "yellow", "🟡", "at_risk"
    return "green", "🟢", "on_track"


def threshold_definitions(thresholds: Thresholds) -> dict[str, object]:
    return {
        "green": "No fail or warn threshold is breached.",
        "yellow": "Only warn thresholds are breached; operator action is needed, but integrity checks are clean.",
        "red": "At least one fail threshold is breached or the monitor errors.",
        "values": thresholds.__dict__,
    }


def alert_fingerprint(status: str, violations: list[dict[str, object]]) -> str:
    keys = ",".join(sorted(f"{item['severity']}:{item['key']}" for item in violations))
    return hashlib.sha256(f"{status}|{keys}".encode("utf-8")).hexdigest()[:16]


def default_secrets_file(env: dict[str, str] | None = None) -> Path:
    source = env or os.environ
    if source.get("SECRETS_FILE"):
        return Path(source["SECRETS_FILE"]).expanduser()
    home = Path(source.get("HOME") or str(Path.home()))
    candidate = home / "jarvis" / ".secrets"
    if candidate.exists():
        return candidate
    return home / ".secrets"


def load_secret_env(secrets_file: Path) -> dict[str, str]:
    if not secrets_file.exists():
        return {}
    command = f"set -a; source {shlex.quote(str(secrets_file))}; env -0"
    proc = subprocess.run(
        ["bash", "-lc", command],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"failed to source {secrets_file}: {stderr}")
    env: dict[str, str] = {}
    for entry in proc.stdout.split(b"\0"):
        if not entry or b"=" not in entry:
            continue
        key, value = entry.split(b"=", 1)
        env[key.decode()] = value.decode(errors="replace")
    return env


def psql_command(env: dict[str, str]) -> list[str]:
    psql_bin = env.get("PSQL_BIN")
    if not psql_bin:
        homebrew_psql = Path("/opt/homebrew/Cellar/postgresql@16/16.13/bin/psql")
        psql_bin = str(homebrew_psql) if homebrew_psql.exists() else "psql"
    return [
        psql_bin,
        "-h",
        env.get("PGHOST", "127.0.0.1"),
        "-U",
        env.get("PGUSER", "jarvisbrain"),
        "-d",
        env.get("PGDATABASE", "jarvis_alpha"),
        "-v",
        "ON_ERROR_STOP=1",
        "-qAtX",
    ]


def run_psql_json(sql: str, env: dict[str, str]) -> Any:
    proc = subprocess.run(
        psql_command(env),
        input=sql,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "psql failed")
    output = proc.stdout.strip()
    if not output:
        return None
    return json.loads(output)


def metrics_sql(alert_suppression_hours: int) -> str:
    hours = max(alert_suppression_hours, 1)
    return f"""
WITH semantic AS (
    SELECT
        COUNT(*)::int AS total_semantic,
        COUNT(*) FILTER (
            WHERE COALESCE(review_status, 'active') = 'active'
        )::int AS active_semantic,
        COUNT(*) FILTER (WHERE review_status = 'pending_review')::int
            AS pending_review,
        COUNT(*) FILTER (WHERE review_status = 'rejected')::int AS rejected,
        COUNT(*) FILTER (WHERE review_status = 'archived')::int AS archived,
        COUNT(*) FILTER (WHERE created_at >= now() - INTERVAL '24 hours')::int
            AS semantic_saves_24h,
        COUNT(*) FILTER (WHERE created_at >= now() - INTERVAL '7 days')::int
            AS semantic_saves_7d,
        COUNT(*) FILTER (
            WHERE review_status = 'pending_review'
              AND created_at >= now() - INTERVAL '24 hours'
        )::int AS review_required_24h
    FROM public.alpha_semantic_memory
),
buddy AS (
    SELECT
        COUNT(*)::int AS memory_buddy_events_7d,
        COUNT(*) FILTER (WHERE read = false)::int AS unread_memory_buddy_events,
        COUNT(*) FILTER (WHERE priority >= 3)::int AS high_priority_buddy_events
    FROM public.alpha_buddy_events
    WHERE created_at >= now() - INTERVAL '7 days'
      AND (
        source = 'semantic_memory_review'
        OR source = '{MONITOR_SOURCE}'
        OR payload ? 'memory_id'
        OR title ILIKE '%memory%'
      )
),
proposal AS (
    SELECT
        COUNT(*) FILTER (
            WHERE p.created_at >= now() - INTERVAL '7 days'
        )::int AS dream_proposals_7d,
        COUNT(*) FILTER (
            WHERE p.executable
              AND p.status IN ('pending_review', 'queued', 'approved')
        )::int AS dream_reviewed_writes_open,
        COUNT(*) FILTER (WHERE p.status = 'queued')::int
            AS dream_proposals_queued,
        COUNT(*) FILTER (WHERE p.status = 'informational')::int
            AS dream_informational_open,
        COUNT(*) FILTER (
            WHERE p.executable
              AND p.status = 'queued'
              AND q.status = 'approved'
        )::int AS dream_approved_waiting_execution,
        COUNT(*) FILTER (WHERE p.status = 'executed')::int
            AS dream_proposals_executed,
        COUNT(*) FILTER (WHERE p.status = 'reverted')::int
            AS dream_proposals_reverted,
        COUNT(*) FILTER (
            WHERE p.executable
              AND p.status IN ('pending_review', 'queued', 'approved')
              AND p.updated_at < now() - INTERVAL '48 hours'
        )::int AS stale_dream_reviewed_writes,
        COUNT(*) FILTER (
            WHERE p.executable
              AND p.status IN ('queued', 'approved')
              AND (
                p.approval_queue_id IS NULL
                OR q.id IS NULL
                OR q.status NOT IN ('pending', 'approved')
                OR q.expires_at IS NULL
                OR q.expires_at <= now()
              )
        )::int AS dream_approval_mismatch_count,
        COUNT(*) FILTER (
            WHERE p.status = 'executed'
              AND l.proposal_id IS NULL
        )::int AS dream_executed_without_ledger
    FROM public.alpha_memory_consolidation_proposals p
    LEFT JOIN public.alpha_approval_queue q
      ON q.id = p.approval_queue_id
    LEFT JOIN public.alpha_memory_consolidation_execution_ledger l
      ON l.proposal_id = p.id
     AND l.status = 'executed'
),
recent_monitor_alerts AS (
    SELECT COALESCE(
        jsonb_agg(payload->>'fingerprint') FILTER (WHERE payload ? 'fingerprint'),
        '[]'::jsonb
    ) AS fingerprints
    FROM public.alpha_buddy_events
    WHERE source = '{MONITOR_SOURCE}'
      AND created_at >= now() - INTERVAL '{hours} hours'
)
SELECT jsonb_build_object(
    'semantic_metrics', to_jsonb(semantic),
    'buddy_metrics', to_jsonb(buddy),
    'proposal_metrics', to_jsonb(proposal),
    'recent_alert_fingerprints', recent_monitor_alerts.fingerprints
)::text
FROM semantic, buddy, proposal, recent_monitor_alerts;
"""


def fetch_metrics(env: dict[str, str], thresholds: Thresholds) -> dict[str, Any]:
    result = run_psql_json(metrics_sql(thresholds.alert_suppression_hours), env)
    if not isinstance(result, dict):
        raise RuntimeError("metrics query returned unexpected shape")
    return result


def cleanup_sql() -> str:
    return "SELECT public.expire_stale_memory_consolidation_proposals()::text;"


def cleanup_stale_memory_consolidation_proposals(env: dict[str, str]) -> dict[str, Any]:
    """Expire stale Dream proposals before evaluating SLO drift."""

    result = run_psql_json(cleanup_sql(), env)
    return result if isinstance(result, dict) else {}


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def post_buddy_event(
    *,
    env: dict[str, str],
    status: str,
    metrics: dict[str, int],
    violations: list[dict[str, object]],
    fingerprint: str,
    thresholds: Thresholds,
) -> str | None:
    event_type = "alert" if status == "fail" else "suggestion"
    priority = 3 if status == "fail" else 2
    title = "Memory observability SLO breached"
    summary = "; ".join(
        f"{item['key']}={item['value']} threshold={item['threshold']}"
        for item in violations[:6]
    )
    body = f"status={status} {summary}"
    payload = {
        "status": status,
        "fingerprint": fingerprint,
        "source": MONITOR_SOURCE,
        "metrics": metrics,
        "violations": violations,
        "thresholds": thresholds.__dict__,
    }
    sql = f"""
SELECT public.record_buddy_event(
    'system',
    {_sql_literal(event_type)},
    {_sql_literal(title)},
    {_sql_literal(body)},
    {priority},
    '{MONITOR_SOURCE}',
    {_sql_literal(json.dumps(payload, sort_keys=True))}::jsonb
)::text;
"""
    result = run_psql_json(
        "SELECT to_jsonb((" + sql.rstrip().rstrip(";") + "))::text;",
        env,
    )
    return str(result) if result else None


def build_report(
    *,
    raw_metrics: dict[str, Any],
    thresholds: Thresholds,
    dry_run: bool,
    no_alert: bool,
    cleanup_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metrics = flatten_metrics(raw_metrics)
    status, violations = evaluate_metrics(metrics, thresholds)
    rag, rag_icon, overall = rag_for_status(status)
    fingerprint = alert_fingerprint(status, violations) if violations else None
    recent_fingerprints = raw_metrics.get("recent_alert_fingerprints") or []
    if not isinstance(recent_fingerprints, list):
        recent_fingerprints = []
    duplicate_suppressed = bool(fingerprint and fingerprint in recent_fingerprints)
    should_alert = bool(
        violations
        and fingerprint
        and not dry_run
        and not no_alert
        and not duplicate_suppressed
    )
    return {
        "status": status,
        "rag": rag,
        "rag_icon": rag_icon,
        "overall": overall,
        "source": MONITOR_SOURCE,
        "checked_at": datetime.now(UTC).isoformat(),
        "metrics": metrics,
        "violations": violations,
        "thresholds": threshold_definitions(thresholds),
        "fingerprint": fingerprint,
        "duplicate_suppressed": duplicate_suppressed,
        "alert_written": False,
        "should_alert": should_alert,
        "cleanup": cleanup_result or {},
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check Alpha memory/Dream observability SLOs",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Evaluate and print JSON without writing Buddy events",
    )
    parser.add_argument(
        "--no-alert",
        action="store_true",
        help="Do not write Buddy events even when SLOs fail",
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

    thresholds = thresholds_from_env(env)
    try:
        cleanup_result = cleanup_stale_memory_consolidation_proposals(env)
        raw_metrics = fetch_metrics(env, thresholds)
        report = build_report(
            raw_metrics=raw_metrics,
            thresholds=thresholds,
            dry_run=args.dry_run,
            no_alert=args.no_alert,
            cleanup_result=cleanup_result,
        )
        if report["should_alert"]:
            event_id = post_buddy_event(
                env=env,
                status=str(report["status"]),
                metrics=report["metrics"],
                violations=report["violations"],
                fingerprint=str(report["fingerprint"]),
                thresholds=thresholds,
            )
            report["alert_written"] = bool(event_id)
            report["buddy_event_id"] = event_id
        print(json.dumps(report, sort_keys=True))
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "source": MONITOR_SOURCE,
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


if __name__ == "__main__":
    raise SystemExit(main())
