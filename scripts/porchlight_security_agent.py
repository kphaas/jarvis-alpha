#!/usr/bin/env python3
"""Porchlight — small scheduled security sweep for JARVIS Alpha.

Porchlight is read-only by design. It scans security posture, writes a JSON
report, and optionally posts one summarized Buddy event through record_buddy_event.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import socket
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Callable

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("SECRETS_FILE", str(Path.home() / "jarvis" / ".secrets"))

from audit_launchagent_drift import parse_launchctl_output  # noqa: E402
from brain.config.node_addresses import GATEWAY_URL  # noqa: E402
from brain.config.secrets import get_secret  # noqa: E402

PSQL_BIN = os.getenv(
    "PORCHLIGHT_PSQL_BIN",
    "/opt/homebrew/Cellar/postgresql@16/16.13/bin/psql",
)
PSQL_DB = os.getenv("PORCHLIGHT_PSQL_DB", "jarvis_alpha")
PSQL_USER = os.getenv("PORCHLIGHT_PSQL_USER", "jarvisbrain")
BRAIN_SSH_TARGET = os.getenv(
    "PORCHLIGHT_BRAIN_SSH_TARGET",
    "jarvisbrain@jarvis-brain.tail40ed36.ts.net",
)
REPORT_PATH = Path(
    os.getenv(
        "PORCHLIGHT_REPORT_PATH",
        str(REPO_ROOT / "logs" / "porchlight_security_report.json"),
    )
)
CLOUDFLARE_ACCESS_URL = os.getenv(
    "PORCHLIGHT_CLOUDFLARE_ACCESS_URL",
    "https://family.kmfh.cloud",
)
PORCHLIGHT_CHANNEL_KEY = "security_alerts"
DEFAULT_PORCHLIGHT_SSH_KEY = Path.home() / ".ssh" / "porchlight_monitor"

NODE_MAP_PATH = SCRIPT_DIR / "node_ssh_map.json"
SECRET_ROTATION_CONFIG = SCRIPT_DIR / "secrets_rotation.json"

SECURITY_LAUNCHAGENTS: dict[str, set[str]] = {
    "brain": {
        "com.jarvis.alpha.rotate.brain_service",
        "com.jarvis.alpha.rotate.buddy",
        "com.jarvis.alpha.pg_backup",
        "com.jarvis.alpha.gmail-health",
    },
    "endpoint": {"com.jarvis.alpha.rotate.endpoint"},
    "gateway": {"com.jarvis.alpha.rotate.gateway"},
    "sandbox": {
        "com.jarvis.alpha.rotate.sandbox",
        "com.jarvis.alpha.restore_drill",
    },
}

TOKEN_LOG_NODES: dict[str, set[str]] = {
    "brain": {"brain", "brain_service"},
    "endpoint": {"endpoint"},
    "gateway": {"gateway"},
    "sandbox": {"sandbox"},
}
TOKEN_LOG_COMMAND = (
    'tail -n 120 "$HOME/jarvis-alpha/logs/token_rotation.log" 2>/dev/null || true'
)

SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


@dataclass
class CheckResult:
    name: str
    status: str
    severity: str
    summary: str
    detail: str = ""
    metadata: dict[str, object] = field(default_factory=dict)


def run_command(
    args: list[str],
    timeout: int = 30,
    input_text: str | None = None,
) -> CommandResult:
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            input=input_text,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CommandResult(1, "", str(exc))
    return CommandResult(result.returncode, result.stdout or "", result.stderr or "")


def run_psql(query: str, timeout: int = 45) -> CommandResult:
    psql_args = [
        PSQL_BIN,
        "-U",
        PSQL_USER,
        "-d",
        PSQL_DB,
        "-t",
        "-A",
        "-F",
        "|",
        "-f",
        "-",
    ]
    node = os.getenv("JARVIS_NODE", "").strip().lower()
    hostname = socket.gethostname().lower()
    if node == "brain" or hostname.startswith("jarvis-brain"):
        return run_command(psql_args, timeout=timeout, input_text=query)

    remote_command = " ".join(shlex.quote(part) for part in psql_args)
    return run_command(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=8",
            BRAIN_SSH_TARGET,
            remote_command,
        ],
        timeout=timeout,
        input_text=query,
    )


def ssh_args_for_probe() -> list[str]:
    args = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=8",
        "-o",
        "StrictHostKeyChecking=yes",
    ]
    key_path = os.getenv("PORCHLIGHT_SSH_KEY", "").strip()
    expanded = Path(key_path).expanduser() if key_path else DEFAULT_PORCHLIGHT_SSH_KEY
    if expanded.is_file():
        args.extend(["-i", str(expanded), "-o", "IdentitiesOnly=yes"])
    return args


def run_ssh(ssh_target: str, remote_command: str, timeout: int = 30) -> CommandResult:
    return run_command(
        [*ssh_args_for_probe(), ssh_target, remote_command],
        timeout=timeout,
    )


def remote_ssh_probe_enabled() -> bool:
    configured = os.getenv("PORCHLIGHT_REMOTE_SSH_ENABLED", "").strip().lower()
    if configured in {"1", "true", "yes"}:
        return True
    key_path = os.getenv("PORCHLIGHT_SSH_KEY", "").strip()
    expanded = Path(key_path).expanduser() if key_path else DEFAULT_PORCHLIGHT_SSH_KEY
    if expanded.is_file():
        return True
    return current_node_name() is None


def current_node_name() -> str | None:
    node = os.getenv("JARVIS_NODE", "").strip().lower()
    if node in SECURITY_LAUNCHAGENTS:
        return node

    hostname = socket.gethostname().lower()
    if hostname.startswith("jarvis-brain"):
        return "brain"
    if hostname.startswith("jarvis-endpoint"):
        return "endpoint"
    if hostname.startswith("jarvis-gateway"):
        return "gateway"
    if hostname.startswith("jarvis-sandbox"):
        return "sandbox"
    return None


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_psql_rows(output: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for raw in output.splitlines():
        line = raw.strip()
        if not line or "|" not in line:
            continue
        rows.append([part.strip() for part in line.split("|")])
    return rows


def highest_severity(results: list[CheckResult]) -> str:
    severity = "info"
    for result in results:
        if SEVERITY_RANK[result.severity] > SEVERITY_RANK[severity]:
            severity = result.severity
    return severity


def check_database_rls(psql: Callable[[str], CommandResult] = run_psql) -> CheckResult:
    query = """
SELECT c.relname,
       c.relrowsecurity::text,
       c.relforcerowsecurity::text,
       COALESCE(p.policy_count, 0)::text
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN (
    SELECT polrelid, COUNT(*) AS policy_count
    FROM pg_policy
    GROUP BY polrelid
) p ON p.polrelid = c.oid
WHERE n.nspname = 'public'
  AND c.relkind = 'r'
  AND c.relname NOT IN ('schema_migrations')
ORDER BY c.relname;
""".strip()
    result = psql(query)
    if result.returncode != 0:
        return CheckResult(
            name="database_rls",
            status="fail",
            severity="critical",
            summary="Could not inspect database RLS posture.",
            detail=(result.stderr or result.stdout).strip()[:500],
        )

    rows = parse_psql_rows(result.stdout)
    if not rows:
        return CheckResult(
            name="database_rls",
            status="warn",
            severity="medium",
            summary="No database table rows were returned for RLS inspection.",
        )

    disabled: list[str] = []
    not_force: list[str] = []
    no_policy: list[str] = []
    for table, rls_enabled, force_enabled, policy_count in rows:
        if rls_enabled != "true":
            disabled.append(table)
        if force_enabled != "true":
            not_force.append(table)
        if policy_count == "0":
            no_policy.append(table)

    issues = []
    if disabled:
        issues.append(f"RLS disabled: {', '.join(disabled[:8])}")
    if not_force:
        issues.append(f"FORCE RLS missing: {', '.join(not_force[:8])}")
    if no_policy:
        issues.append(f"No RLS policy: {', '.join(no_policy[:8])}")

    if disabled or not_force:
        return CheckResult(
            name="database_rls",
            status="fail",
            severity="critical" if disabled else "high",
            summary="Database RLS posture needs attention.",
            detail="; ".join(issues),
            metadata={
                "total_tables": len(rows),
                "disabled": disabled,
                "not_force": not_force,
                "no_policy": no_policy,
            },
        )

    if no_policy:
        return CheckResult(
            name="database_rls",
            status="warn",
            severity="medium",
            summary="All tables have FORCE RLS, but some have no policy.",
            detail="; ".join(issues),
            metadata={"total_tables": len(rows), "no_policy": no_policy},
        )

    return CheckResult(
        name="database_rls",
        status="pass",
        severity="info",
        summary=f"RLS and FORCE RLS are enabled on {len(rows)} public tables.",
        metadata={"total_tables": len(rows)},
    )


def check_secret_rotation(
    psql: Callable[[str], CommandResult] = run_psql,
    config_path: Path = SECRET_ROTATION_CONFIG,
    today: date | None = None,
) -> CheckResult:
    today = today or datetime.now(UTC).date()
    query = """
SELECT secret_name,
       COALESCE(last_rotated_at::date::text, ''),
       rotation_days::text,
       next_due_at::text,
       days_until_due::text,
       COALESCE(last_verify_status, '')
FROM v_secret_rotation_status
ORDER BY secret_name;
""".strip()
    result = psql(query)
    if result.returncode != 0:
        return CheckResult(
            name="secret_rotation",
            status="fail",
            severity="high",
            summary="Could not inspect secret rotation ledger.",
            detail=(result.stderr or result.stdout).strip()[:500],
        )

    rows = parse_psql_rows(result.stdout)
    config = load_json(config_path)
    configured = config.get("secrets", {})
    seen: dict[str, dict[str, str]] = {}
    issues: list[str] = []
    warnings: list[str] = []

    for row in rows:
        if len(row) < 6:
            continue
        name, rotated, days, next_due, days_until, verify = row[:6]
        seen[name] = {
            "last_rotated": rotated,
            "rotation_days": days,
            "next_due_at": next_due,
            "days_until_due": days_until,
            "last_verify_status": verify,
        }
        due_date = datetime.strptime(next_due, "%Y-%m-%d").date()
        days_left = (due_date - today).days
        if verify == "failed":
            issues.append(f"{name} last verification failed")
        if days_left < 0:
            issues.append(f"{name} overdue since {next_due}")
        elif days_left == 0:
            issues.append(f"{name} due today")
        elif days_left <= 14:
            warnings.append(f"{name} due in {days_left} days")

    for name, spec in configured.items():
        if name in seen:
            continue
        if spec.get("requires_alter_role"):
            warnings.append(f"{name} is manual DB rotation and has no ledger row")
        else:
            issues.append(f"{name} missing from rotation ledger")

    if issues:
        return CheckResult(
            name="secret_rotation",
            status="fail",
            severity="critical",
            summary="One or more secrets are due, overdue, failed, or untracked.",
            detail="; ".join((issues + warnings)[:10]),
            metadata={"issues": issues, "warnings": warnings, "secrets": seen},
        )

    if warnings:
        return CheckResult(
            name="secret_rotation",
            status="warn",
            severity="medium",
            summary="Secret rotation has upcoming/manual items to review.",
            detail="; ".join(warnings[:10]),
            metadata={"warnings": warnings, "secrets": seen},
        )

    return CheckResult(
        name="secret_rotation",
        status="pass",
        severity="info",
        summary=f"Secret rotation ledger is healthy for {len(seen)} tracked secrets.",
        metadata={"secrets": seen},
    )


def check_security_launchagents(
    node_map: dict[str, dict[str, str]] | None = None,
    ssh: Callable[[str, str], CommandResult] = run_ssh,
) -> CheckResult:
    node_map = node_map or load_json(NODE_MAP_PATH)
    local_node = current_node_name()
    remote_probe_enabled = remote_ssh_probe_enabled()
    missing_by_node: dict[str, list[str]] = {}
    unreachable: dict[str, str] = {}
    loaded_by_node: dict[str, list[str]] = {}
    skipped_remote: dict[str, str] = {}

    for node, expected in SECURITY_LAUNCHAGENTS.items():
        if node == local_node:
            result = run_command(["launchctl", "list"])
        else:
            if not remote_probe_enabled:
                skipped_remote[node] = "remote SSH probe not configured"
                continue
            target = node_map[node]["ssh_target"]
            result = ssh(target, "launchctl list")
        if result.returncode != 0:
            unreachable[node] = (result.stderr or result.stdout).strip()[:300]
            continue
        loaded = parse_launchctl_output(result.stdout)
        loaded_by_node[node] = sorted(label for label in loaded if label in expected)
        missing = sorted(expected - loaded)
        if missing:
            missing_by_node[node] = missing

    if unreachable or missing_by_node:
        parts = []
        for node, labels in missing_by_node.items():
            parts.append(f"{node} missing {', '.join(labels)}")
        for node in unreachable:
            parts.append(f"{node} unreachable")
        return CheckResult(
            name="security_launchagents",
            status="fail",
            severity="high",
            summary="One or more security LaunchAgents are not confirmed loaded.",
            detail="; ".join(parts),
            metadata={
                "missing_by_node": missing_by_node,
                "unreachable": unreachable,
                "loaded_by_node": loaded_by_node,
                "skipped_remote": skipped_remote,
            },
        )

    if skipped_remote:
        local_count = sum(len(labels) for labels in loaded_by_node.values())
        return CheckResult(
            name="security_launchagents",
            status="warn",
            severity="medium",
            summary="Local security LaunchAgents are loaded, but remote nodes were not probed.",
            detail="; ".join(f"{node}: {msg}" for node, msg in skipped_remote.items()),
            metadata={
                "loaded_by_node": loaded_by_node,
                "skipped_remote": skipped_remote,
                "local_loaded_count": local_count,
            },
        )

    total = sum(len(labels) for labels in SECURITY_LAUNCHAGENTS.values())
    return CheckResult(
        name="security_launchagents",
        status="pass",
        severity="info",
        summary=f"All {total} security LaunchAgents are loaded.",
        metadata={"loaded_by_node": loaded_by_node},
    )


def parse_json_log_lines(text: str) -> list[dict]:
    records = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            records.append(payload)
    return records


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_successful_rotation_record(record: dict) -> bool:
    message = str(record.get("message", "")).lower()
    return "rotation complete" in message or "rotation skipped" in message


def check_token_rotation_logs(
    node_map: dict[str, dict[str, str]] | None = None,
    ssh: Callable[[str, str], CommandResult] = run_ssh,
    now: datetime | None = None,
    max_age_hours: int = 36,
) -> CheckResult:
    node_map = node_map or load_json(NODE_MAP_PATH)
    local_node = current_node_name()
    remote_probe_enabled = remote_ssh_probe_enabled()
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(hours=max_age_hours)
    stale: dict[str, str] = {}
    recent: dict[str, str] = {}
    skipped_remote: dict[str, str] = {}

    for node, expected_log_nodes in TOKEN_LOG_NODES.items():
        if node == local_node:
            result = run_command(["/bin/sh", "-lc", TOKEN_LOG_COMMAND])
        else:
            if not remote_probe_enabled:
                skipped_remote[node] = "remote SSH probe not configured"
                continue
            target = node_map[node]["ssh_target"]
            result = ssh(target, TOKEN_LOG_COMMAND)
        if result.returncode != 0:
            stale[node] = "could not read token_rotation.log"
            continue
        records = parse_json_log_lines(result.stdout)
        for log_node in expected_log_nodes:
            candidates = [
                rec
                for rec in records
                if rec.get("node") == log_node and _is_successful_rotation_record(rec)
            ]
            latest = max(
                candidates,
                key=lambda rec: (
                    _parse_timestamp(rec.get("timestamp"))
                    or datetime.min.replace(tzinfo=UTC)
                ),
                default=None,
            )
            latest_ts = _parse_timestamp(latest.get("timestamp")) if latest else None
            if latest_ts and latest_ts >= cutoff:
                recent[log_node] = latest_ts.isoformat()
            else:
                stale[log_node] = (
                    "no successful rotation record within freshness window"
                )

    if stale:
        return CheckResult(
            name="token_rotation_logs",
            status="fail",
            severity="high",
            summary="Some service-token rotation logs are stale or missing.",
            detail="; ".join(f"{node}: {msg}" for node, msg in stale.items()),
            metadata={
                "stale": stale,
                "recent": recent,
                "skipped_remote": skipped_remote,
                "max_age_hours": max_age_hours,
            },
        )

    if skipped_remote:
        return CheckResult(
            name="token_rotation_logs",
            status="warn",
            severity="medium",
            summary="Local service-token logs are fresh, but remote nodes were not probed.",
            detail="; ".join(f"{node}: {msg}" for node, msg in skipped_remote.items()),
            metadata={
                "recent": recent,
                "skipped_remote": skipped_remote,
                "max_age_hours": max_age_hours,
            },
        )

    return CheckResult(
        name="token_rotation_logs",
        status="pass",
        severity="info",
        summary=f"All service-token rotators have a fresh success within {max_age_hours} hours.",
        metadata={"recent": recent, "max_age_hours": max_age_hours},
    )


def _parse_http_headers(text: str) -> tuple[int | None, dict[str, str]]:
    status: int | None = None
    headers: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.upper().startswith("HTTP/"):
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                status = int(parts[1])
            headers = {}
            continue
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()
    return status, headers


def check_cloudflare_access(
    url: str = CLOUDFLARE_ACCESS_URL,
    command: Callable[..., CommandResult] = run_command,
) -> CheckResult:
    result = command(
        [
            "curl",
            "-sS",
            "-I",
            "--max-time",
            "15",
            url,
        ],
        timeout=20,
    )
    if result.returncode != 0:
        return CheckResult(
            name="cloudflare_access",
            status="fail",
            severity="high",
            summary=f"Could not reach {url}.",
            detail=(result.stderr or result.stdout).strip()[:500],
        )

    status, headers = _parse_http_headers(result.stdout)
    location = headers.get("location", "")
    authenticate = headers.get("www-authenticate", "")
    gated = status in (301, 302, 303, 307, 308, 401, 403) and (
        "cloudflareaccess.com" in location or "Cloudflare-Access" in authenticate
    )
    if not gated:
        return CheckResult(
            name="cloudflare_access",
            status="fail",
            severity="critical",
            summary=f"{url} did not look protected by Cloudflare Access.",
            detail=f"status={status} location={location[:160]} www-authenticate={authenticate[:160]}",
            metadata={"status": status, "location": location},
        )
    return CheckResult(
        name="cloudflare_access",
        status="pass",
        severity="info",
        summary=f"{url} is gated by Cloudflare Access before origin.",
        metadata={"status": status},
    )


def build_report(checks: list[CheckResult]) -> dict[str, object]:
    failing = [check for check in checks if check.status == "fail"]
    warning = [check for check in checks if check.status == "warn"]
    severity = highest_severity(checks)
    status = "pass"
    if failing:
        status = "fail"
    elif warning:
        status = "warn"
    return {
        "agent": "Porchlight",
        "generated_at": datetime.now(UTC).isoformat(),
        "status": status,
        "severity": severity,
        "counts": {
            "checks": len(checks),
            "failing": len(failing),
            "warning": len(warning),
            "passing": sum(1 for check in checks if check.status == "pass"),
        },
        "checks": [asdict(check) for check in checks],
    }


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def buddy_event_body(report: dict[str, object]) -> str:
    counts = report["counts"]
    lines = [
        f"Status: {report['status']} / severity: {report['severity']}",
        (
            f"Checks: {counts['passing']} pass, "
            f"{counts['warning']} warning, {counts['failing']} failing"
        ),
    ]
    issues = [
        check for check in report["checks"] if check["status"] in {"fail", "warn"}
    ]
    for check in issues[:6]:
        detail = f" — {check['detail']}" if check.get("detail") else ""
        lines.append(f"- {check['name']}: {check['summary']}{detail}")
    return "\n".join(lines)[:3500]


def post_buddy_event(
    report: dict[str, object],
    psql: Callable[[str], CommandResult] = run_psql,
) -> CommandResult:
    status = str(report["status"])
    event_type = "alert" if status in {"fail", "warn"} else "system"
    priority = 3 if report["severity"] in {"high", "critical"} else 2
    title = (
        "Porchlight security alert"
        if event_type == "alert"
        else "Porchlight security sweep"
    )
    body = buddy_event_body(report)
    payload = json.dumps(report, separators=(",", ":"), default=str)
    query = f"""
SELECT public.record_buddy_event(
  NULL,
  {_sql_literal(event_type)},
  {_sql_literal(title)},
  {_sql_literal(body)},
  {priority},
  'porchlight',
  {_sql_literal(payload)}::jsonb
);
""".strip()
    return psql(query)


def agent_event_severity(report: dict[str, object]) -> str:
    if report["status"] == "pass":
        return "info"
    if report["status"] == "warn":
        return "warning"
    if report["severity"] == "critical":
        return "critical"
    return "error"


def agent_event_type(report: dict[str, object]) -> str:
    if report["status"] == "pass":
        return "security.sweep_ok"
    if report["status"] == "warn":
        return "security.sweep_warning"
    return "security.sweep_failed"


def agent_event_title(report: dict[str, object]) -> str:
    if report["status"] == "pass":
        return "Porchlight security sweep"
    return "Porchlight security alert"


def record_agent_event(
    report: dict[str, object],
    *,
    notification_status: str,
    psql: Callable[[str], CommandResult] = run_psql,
) -> CommandResult:
    payload = json.dumps(report, separators=(",", ":"), default=str)
    query = f"""
SELECT public.record_agent_event(
  'porchlight',
  {_sql_literal(agent_event_type(report))},
  {_sql_literal(agent_event_title(report))},
  {_sql_literal(buddy_event_body(report))},
  {_sql_literal(agent_event_severity(report))},
  {_sql_literal(payload)}::jsonb,
  NULL,
  {_sql_literal("porchlight:" + str(report["generated_at"]))},
  '{PORCHLIGHT_CHANNEL_KEY}',
  {_sql_literal(notification_status)}
);
""".strip()
    return psql(query)


def mark_agent_event_notification(
    event_id: str,
    status: str,
    *,
    result: dict[str, object] | None = None,
    error: str | None = None,
    psql: Callable[[str], CommandResult] = run_psql,
) -> CommandResult:
    payload = json.dumps(result or {}, separators=(",", ":"), default=str)
    error_sql = "NULL" if error is None else _sql_literal(error[:500])
    query = f"""
SELECT public.mark_agent_event_notification(
  {_sql_literal(event_id)}::uuid,
  {_sql_literal(status)},
  {_sql_literal(payload)}::jsonb,
  {error_sql}
);
""".strip()
    return psql(query)


def notify_mattermost(
    report: dict[str, object],
    *,
    command: Callable[..., CommandResult] = run_command,
) -> tuple[str, dict[str, object]]:
    payload = {
        "title": agent_event_title(report),
        "message": buddy_event_body(report),
        "severity": agent_event_severity(report),
        "source": "alpha",
        "channel_key": PORCHLIGHT_CHANNEL_KEY,
    }
    result = command(
        [
            "curl",
            "-sk",
            "-m",
            "15",
            "-X",
            "POST",
            "-H",
            "Content-Type: application/json",
            "-H",
            f"Authorization: Bearer {get_secret('GATEWAY_TOKEN')}",
            "-H",
            f"X-JARVIS-Idempotency-Key: porchlight:{report['generated_at']}",
            "-d",
            json.dumps(payload),
            f"{GATEWAY_URL.rstrip('/')}/v1/notify/mattermost",
        ],
        timeout=20,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip()[:500])
    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("gateway_non_json_response") from exc
    if parsed.get("status") != "sent":
        raise RuntimeError(str(parsed.get("detail") or "gateway_rejected"))
    return str(parsed.get("channel_key") or PORCHLIGHT_CHANNEL_KEY), parsed


def post_agent_event_alert(
    report: dict[str, object],
    *,
    psql: Callable[[str], CommandResult] = run_psql,
    command: Callable[..., CommandResult] = run_command,
) -> CommandResult:
    event_result = record_agent_event(report, notification_status="pending", psql=psql)
    if event_result.returncode != 0:
        return event_result
    event_id = event_result.stdout.strip().splitlines()[-1].strip()
    if not event_id:
        return CommandResult(1, "", "record_agent_event returned no event id")

    try:
        _channel_key, notify_result = notify_mattermost(report, command=command)
    except Exception as exc:
        mark_agent_event_notification(
            event_id,
            "failed",
            result={"provider": "mattermost"},
            error=str(exc),
            psql=psql,
        )
        return CommandResult(1, "", str(exc))

    mark_result = mark_agent_event_notification(
        event_id,
        "sent",
        result=notify_result,
        psql=psql,
    )
    if mark_result.returncode != 0:
        return mark_result
    return CommandResult(0, event_id, "")


def write_report(report: dict[str, object], path: Path = REPORT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def run_sweep(args: argparse.Namespace) -> dict[str, object]:
    node_map = load_json(NODE_MAP_PATH)
    checks = [
        check_database_rls(),
        check_secret_rotation(),
        check_security_launchagents(node_map=node_map),
        check_token_rotation_logs(
            node_map=node_map,
            max_age_hours=args.max_token_log_age_hours,
        ),
        check_cloudflare_access(args.cloudflare_access_url),
    ]
    return build_report(checks)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Porchlight security sweep for JARVIS Alpha",
    )
    parser.add_argument("--json", action="store_true", help="Print full JSON report")
    parser.add_argument(
        "--always-report",
        action="store_true",
        help="Post a notification event even when every check passes",
    )
    parser.add_argument(
        "--report-warnings",
        action="store_true",
        help="Post a notification event for warnings as well as failures",
    )
    parser.add_argument(
        "--no-buddy-event",
        action="store_true",
        help="Do not post Buddy, Alpha agent, or Mattermost notifications",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 2 when Porchlight finds warning/failing checks",
    )
    parser.add_argument(
        "--max-token-log-age-hours",
        type=int,
        default=36,
        help="Freshness window for token rotation success logs",
    )
    parser.add_argument(
        "--cloudflare-access-url",
        default=CLOUDFLARE_ACCESS_URL,
        help="Public URL expected to be gated by Cloudflare Access",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_sweep(args)
    write_report(report)

    should_post = (
        args.always_report
        or report["status"] == "fail"
        or (args.report_warnings and report["status"] == "warn")
    )
    if not args.no_buddy_event and should_post:
        agent_result = post_agent_event_alert(report)
        if agent_result.returncode != 0:
            print(
                "Porchlight: Alpha agent/Mattermost alert failed: "
                + (agent_result.stderr or agent_result.stdout).strip(),
                file=sys.stderr,
            )

        event_result = post_buddy_event(report)
        if event_result.returncode != 0:
            print(
                "Porchlight: Buddy event post failed: "
                + (event_result.stderr or event_result.stdout).strip(),
                file=sys.stderr,
            )

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        counts = report["counts"]
        print(
            "Porchlight "
            f"{report['status']} ({report['severity']}): "
            f"{counts['passing']} pass, {counts['warning']} warn, "
            f"{counts['failing']} fail"
        )
        print(f"Report: {REPORT_PATH}")

    if args.strict and report["status"] != "pass":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
