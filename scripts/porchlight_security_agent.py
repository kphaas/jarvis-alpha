#!/usr/bin/env python3
"""Porchlight — small scheduled security sweep for JARVIS Alpha.

Porchlight is read-only by design. It scans security posture, writes a JSON
report, and optionally posts one summarized Buddy event through record_buddy_event.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shlex
import socket
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from fnmatch import fnmatch
from pathlib import Path
from typing import Callable
from urllib.parse import urlencode, urlparse

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
CLOUDFLARE_API_BASE = os.getenv(
    "PORCHLIGHT_CLOUDFLARE_API_BASE",
    "https://api.cloudflare.com/client/v4",
)
PORCHLIGHT_CHANNEL_KEY = "security_alerts"
DEFAULT_PORCHLIGHT_SSH_KEY = Path.home() / ".ssh" / "porchlight_monitor"

NODE_MAP_PATH = SCRIPT_DIR / "node_ssh_map.json"
SECRET_ROTATION_CONFIG = SCRIPT_DIR / "secrets_rotation.json"
ROUTES_DIR = REPO_ROOT / "brain" / "routes"
PYTHON_REQUIREMENTS = (REPO_ROOT / "requirements.txt",)
UI_DIR = REPO_ROOT / "ui"
NPM_BIN = os.getenv(
    "PORCHLIGHT_NPM_BIN",
    str(Path("/opt/homebrew/bin/npm"))
    if Path("/opt/homebrew/bin/npm").exists()
    else "npm",
)
SECRET_VERIFY_MAX_AGE_HOURS = 36
JWT_VERIFY_MIN_HOURS = 24
DEFAULT_CLOUDFLARE_EXPECTED_ACTORS = {"kennethphaas@gmail.com"}
DEFAULT_CLOUDFLARE_FORBIDDEN_HOST_PATTERNS = (
    "alpha.*",
    "brain.*",
    "jarvis-brain.*",
    "*.jarvis-brain.*",
)
DEFAULT_CLOUDFLARE_FORBIDDEN_APP_TERMS = (
    "alpha",
    "brain",
    "jarvis brain",
    "jarvis-brain",
)
DEFAULT_GITHUB_BRANCH_PROTECTION_REPOS = ("kphaas/jarvis-alpha",)
ACCEPTED_BOOTSTRAP_SECDEF_FUNCTIONS = {
    "public.pgaudit_ddl_command_end()",
    "public.pgaudit_sql_drop()",
}

SECURITY_LAUNCHAGENTS: dict[str, set[str]] = {
    "brain": {
        "com.jarvis.alpha.rotate.brain_service",
        "com.jarvis.alpha.rotate.buddy",
        "com.jarvis.alpha.pg_backup",
        "com.jarvis.alpha.gmail-health",
        "com.jarvis.alpha.sweep-cert-renewal.brain",
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
REVIEWED_ROUTE_DB_ACCESS: dict[str, str] = {
    "approvals.py": "PIN bootstrap reads Ken profile before request RLS exists; decisions use rls_connection/SECDEF.",
    "briefings.py": "Briefing ingestion/read paths are scope-gated service/admin routes; follow-up is to migrate to explicit service RLS context.",
    "chat.py": "Primary chat persistence uses rls_connection; remaining direct access is a legacy compatibility path pending route split.",
    "costs.py": "Cost collection is admin/service-scoped infrastructure data, not child profile content.",
    "dev.py": "Development-only diagnostics; protected by auth middleware outside explicit skip paths.",
    "dream.py": "Dream control plane uses service/admin paths with platform-admin policies; broader refactor is tracked separately.",
    "dream_planning.py": "Model policy lookup is platform-admin service configuration and sets rls.role inside transaction.",
    "internal_cost.py": "Internal cost ingestion is service-scoped and explicitly checks cost.report scope.",
    "pin_auth.py": "Authentication bootstrap must read active profiles before issuing JWT/RLS context.",
    "prompts.py": "Prompt registry is global system configuration; write path is auth-protected and pending RLS wrapper.",
    "watchdog.py": "Watchdog ingest path is service-scoped; user-facing events use rls_connection.",
}


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
    env: dict[str, str] | None = None,
) -> CommandResult:
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            input=input_text,
            text=True,
            timeout=timeout,
            check=False,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CommandResult(1, "", str(exc))
    return CommandResult(result.returncode, result.stdout or "", result.stderr or "")


def _postgres_password() -> str | None:
    password = os.getenv("POSTGRES_PASSWORD", "").strip()
    if password:
        return password
    try:
        return get_secret("POSTGRES_PASSWORD").strip()
    except KeyError:
        return None


def run_psql(query: str, timeout: int = 45) -> CommandResult:
    password = _postgres_password()
    use_password_auth = PSQL_USER == "jarvisbrain" or password is not None
    psql_args = [
        PSQL_BIN,
        *(["-h", "localhost"] if use_password_auth else []),
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
        env = os.environ.copy()
        if password:
            env["PGPASSWORD"] = password
        return run_command(psql_args, timeout=timeout, input_text=query, env=env)

    remote_command = " ".join(shlex.quote(part) for part in psql_args)
    remote_command = (
        "cd ~/jarvis-alpha && set -a && source ~/jarvis/.secrets && set +a && "
        f'PGPASSWORD="$POSTGRES_PASSWORD" {remote_command}'
    )
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


def check_postgres_role_safety(
    psql: Callable[[str], CommandResult] = run_psql,
) -> CheckResult:
    query = """
SELECT rolname,
       rolsuper::text,
       rolbypassrls::text,
       rolcreatedb::text,
       rolcreaterole::text,
       rolcanlogin::text
FROM pg_roles
WHERE rolname IN (
    'jarvisbrain',
    'jarvis_alpha_writer',
    'jarvis_alpha_app',
    'jarvis_alpha_owner',
    'jarvis_pg_breakglass'
)
   OR rolsuper
ORDER BY rolname;
""".strip()
    result = psql(query)
    if result.returncode != 0:
        return CheckResult(
            name="postgres_role_safety",
            status="fail",
            severity="critical",
            summary="Could not inspect Postgres role safety posture.",
            detail=(result.stderr or result.stdout).strip()[:500],
        )

    rows = parse_psql_rows(result.stdout)
    if not rows:
        return CheckResult(
            name="postgres_role_safety",
            status="fail",
            severity="critical",
            summary="No Postgres role rows were returned for safety inspection.",
        )

    roles = {
        row[0]: {
            "rolsuper": row[1] == "true",
            "rolbypassrls": row[2] == "true",
            "rolcreatedb": row[3] == "true",
            "rolcreaterole": row[4] == "true",
            "rolcanlogin": row[5] == "true",
        }
        for row in rows
        if len(row) >= 6
    }
    missing_required = sorted(
        {"jarvisbrain", "jarvis_alpha_writer", "jarvis_alpha_app"} - set(roles)
    )
    missing_containment = sorted(
        {"jarvis_alpha_owner", "jarvis_pg_breakglass"} - set(roles)
    )
    superusers = sorted(
        name for name, attrs in roles.items() if attrs.get("rolsuper") is True
    )
    runtime_bypass = sorted(
        name
        for name in ("jarvis_alpha_writer", "jarvis_alpha_app")
        if roles.get(name, {}).get("rolsuper")
        or roles.get(name, {}).get("rolbypassrls")
    )

    issues: list[str] = []
    if missing_required:
        issues.append("missing required role(s): " + ", ".join(missing_required))
    if runtime_bypass:
        issues.append("runtime role(s) can bypass RLS: " + ", ".join(runtime_bypass))
    jarvisbrain_superuser = roles.get("jarvisbrain", {}).get("rolsuper") is True
    secdef_metadata: dict[str, object] = {}
    if jarvisbrain_superuser:
        if roles.get("jarvisbrain", {}).get("rolbypassrls"):
            issues.append("jarvisbrain still has BYPASSRLS")
        if missing_containment:
            issues.append(
                "missing bootstrap containment role(s): "
                + ", ".join(missing_containment)
            )
        if superusers == ["jarvisbrain"]:
            issues.append(
                "jarvisbrain is the only superuser; demotion needs break-glass first"
            )
        if not issues:
            secdef_ok, secdef_detail, secdef_metadata = (
                _check_security_definer_owner_containment(psql)
            )
            if not secdef_ok:
                issues.append(secdef_detail)

    if jarvisbrain_superuser and issues:
        issues.insert(
            0,
            "jarvisbrain is still SUPERUSER and can bypass FORCE RLS until containment is complete",
        )

    if issues:
        return CheckResult(
            name="postgres_role_safety",
            status="fail",
            severity="critical",
            summary="Postgres role safety needs remediation before strict production readiness.",
            detail="; ".join(issues),
            metadata={
                "superusers": superusers,
                "runtime_bypass_roles": runtime_bypass,
                "missing_required_roles": missing_required,
                "missing_containment_roles": missing_containment,
                "jarvisbrain": roles.get("jarvisbrain", {}),
                "security_definer": secdef_metadata,
            },
        )

    if jarvisbrain_superuser:
        return CheckResult(
            name="postgres_role_safety",
            status="warn",
            severity="medium",
            summary="Postgres bootstrap superuser risk is accepted and contained.",
            detail=(
                "jarvisbrain remains a bootstrap superuser, but runtime roles are "
                "NOBYPASSRLS, break-glass exists, and SECURITY DEFINER functions "
                "are owned by jarvis_alpha_owner except accepted pgaudit handlers."
            ),
            metadata={
                "superusers": superusers,
                "runtime_bypass_roles": runtime_bypass,
                "missing_required_roles": missing_required,
                "missing_containment_roles": missing_containment,
                "jarvisbrain": roles.get("jarvisbrain", {}),
                "security_definer": secdef_metadata,
                "bootstrap_risk": "accepted_contained",
            },
        )

    return CheckResult(
        name="postgres_role_safety",
        status="pass",
        severity="info",
        summary="Postgres runtime roles are NOBYPASSRLS and jarvisbrain is not superuser.",
        metadata={"superusers": superusers},
    )


def _check_security_definer_owner_containment(
    psql: Callable[[str], CommandResult],
) -> tuple[bool, str, dict[str, object]]:
    query = """
SELECT format('%I.%I(%s)',
              n.nspname,
              p.proname,
              pg_get_function_identity_arguments(p.oid)),
       pg_get_userbyid(p.proowner),
       l.lanname
FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
JOIN pg_language l ON l.oid = p.prolang
WHERE p.prosecdef
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND n.nspname NOT LIKE 'pg_toast%'
ORDER BY n.nspname, p.proname, pg_get_function_identity_arguments(p.oid);
""".strip()
    result = psql(query)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[:500]
        return (
            False,
            "could not inspect SECURITY DEFINER ownership: " + detail,
            {"error": detail},
        )

    rows = parse_psql_rows(result.stdout)
    if not rows:
        return False, "no SECURITY DEFINER rows returned", {"total": 0}

    owner_counts: dict[str, int] = {}
    accepted_bootstrap: list[str] = []
    unexpected: list[str] = []
    malformed = 0
    for row in rows:
        if len(row) < 3:
            malformed += 1
            continue
        identity, owner, language = row[:3]
        owner_counts[owner] = owner_counts.get(owner, 0) + 1
        if owner == "jarvis_alpha_owner":
            continue
        if (
            owner == "jarvisbrain"
            and language == "c"
            and identity in ACCEPTED_BOOTSTRAP_SECDEF_FUNCTIONS
        ):
            accepted_bootstrap.append(identity)
            continue
        unexpected.append(f"{identity} owned by {owner}")

    metadata = {
        "total": len(rows),
        "owner_counts": owner_counts,
        "accepted_bootstrap": accepted_bootstrap,
        "unexpected": unexpected,
        "malformed_rows": malformed,
    }
    if malformed:
        return (
            False,
            f"{malformed} SECURITY DEFINER row(s) could not be parsed",
            metadata,
        )
    if unexpected:
        return (
            False,
            "unexpected SECURITY DEFINER owner(s): " + "; ".join(unexpected[:5]),
            metadata,
        )
    return True, "", metadata


def _pg_hba_csv_items(value: str) -> set[str]:
    cleaned = value.strip().strip("{}")
    if not cleaned:
        return set()
    return {part.strip().strip('"') for part in cleaned.split(",") if part.strip()}


def check_postgres_hba_safety(
    psql: Callable[[str], CommandResult] = run_psql,
) -> CheckResult:
    query = """
SELECT line_number::text,
       type,
       array_to_string(database, ','),
       array_to_string(user_name, ','),
       COALESCE(address, ''),
       auth_method,
       COALESCE(error, '')
FROM pg_hba_file_rules
ORDER BY line_number;
""".strip()
    result = psql(query)
    if result.returncode != 0:
        return CheckResult(
            name="postgres_hba_safety",
            status="fail",
            severity="critical",
            summary="Could not inspect Postgres client authentication rules.",
            detail=(result.stderr or result.stdout).strip()[:500],
        )

    rows = parse_psql_rows(result.stdout)
    if not rows:
        return CheckResult(
            name="postgres_hba_safety",
            status="fail",
            severity="critical",
            summary="No pg_hba rules were returned for safety inspection.",
        )

    broad_trust_rules: list[str] = []
    parser_errors: list[str] = []
    malformed_rows = 0
    trust_rule_count = 0

    for row in rows:
        if len(row) < 7:
            malformed_rows += 1
            continue
        (
            line_number,
            rule_type,
            databases_raw,
            users_raw,
            address,
            auth_method,
            error,
        ) = row[:7]
        if error:
            parser_errors.append(f"line {line_number}: {error[:120]}")
        if auth_method != "trust":
            continue

        trust_rule_count += 1
        databases = _pg_hba_csv_items(databases_raw)
        users = _pg_hba_csv_items(users_raw)
        is_loopback = address in {"", "127.0.0.1", "127.0.0.1/32", "::1", "::1/128"}
        is_broad = "all" in databases and "all" in users
        if (
            rule_type in {"local", "host", "hostssl", "hostnossl"}
            and is_loopback
            and is_broad
        ):
            if rule_type == "local":
                broad_trust_rules.append(f"line {line_number}: local all/all trust")
            else:
                broad_trust_rules.append(
                    f"line {line_number}: {rule_type} {address} all/all trust"
                )

    issues = []
    if parser_errors:
        issues.append("pg_hba parse errors: " + "; ".join(parser_errors[:3]))
    if malformed_rows:
        issues.append(f"{malformed_rows} pg_hba row(s) could not be parsed")
    if broad_trust_rules:
        issues.append("broad local trust auth: " + "; ".join(broad_trust_rules[:5]))

    if issues:
        return CheckResult(
            name="postgres_hba_safety",
            status="fail",
            severity="critical",
            summary="Postgres client authentication is not safe for break-glass demotion.",
            detail="; ".join(issues),
            metadata={
                "total_rules": len(rows),
                "trust_rule_count": trust_rule_count,
                "broad_trust_rules": broad_trust_rules,
                "parser_errors": parser_errors,
                "malformed_rows": malformed_rows,
            },
        )

    return CheckResult(
        name="postgres_hba_safety",
        status="pass",
        severity="info",
        summary="Postgres client authentication has no broad local trust rules.",
        metadata={"total_rules": len(rows), "trust_rule_count": trust_rule_count},
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


def _decode_jwt_payload(token: str) -> dict[str, object]:
    parts = token.split(".")
    if len(parts) < 2:
        raise ValueError("not a JWT")
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    return json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))


def _verify_jwt_exp(
    token: str,
    *,
    now: datetime | None = None,
    min_hours: float = JWT_VERIFY_MIN_HOURS,
) -> tuple[str, str]:
    now = now or datetime.now(UTC)
    try:
        payload = _decode_jwt_payload(token)
        exp = int(payload["exp"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return (
            "failed",
            f"JWT expiration could not be decoded: {exc.__class__.__name__}",
        )
    expires_at = datetime.fromtimestamp(exp, tz=UTC)
    hours_left = (expires_at - now).total_seconds() / 3600
    if hours_left <= 0:
        return "failed", "JWT is expired"
    if hours_left < min_hours:
        return "warning", f"JWT expires in {hours_left:.1f} hours"
    return "passed", f"JWT expires in {hours_left:.1f} hours"


def _remote_jwt_verify(
    node: str,
    secret_key: str,
    node_map: dict[str, dict[str, str]],
    *,
    min_hours: float = JWT_VERIFY_MIN_HOURS,
    ssh: Callable[[str, str], CommandResult] = run_ssh,
) -> tuple[str, str]:
    node_info = node_map.get(node)
    if not node_info:
        return "skipped", "node is not in SSH map"
    if not remote_ssh_probe_enabled():
        return "skipped", "remote SSH probe not configured"
    if secret_key != "ALPHA_SERVICE_TOKEN":
        return "skipped", f"remote JWT key {secret_key} is not allowlisted"
    command = f"porchlight jwt-exp {secret_key} {min_hours:g}"
    result = ssh(node_info["ssh_target"], command)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[:160]
        return "failed", f"remote JWT probe failed: {detail or 'ssh command failed'}"
    try:
        payload = json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        return "failed", "remote JWT probe returned invalid JSON"
    status = str(payload.get("status") or "failed")
    detail = str(payload.get("detail") or "")
    if status not in {"passed", "warning", "failed", "skipped"}:
        return "failed", "remote JWT probe returned invalid status"
    return status, detail


def _secret_value_for_probe(name: str, spec: dict[str, object]) -> str | None:
    key = str(spec.get("secret_key") or name)
    try:
        return get_secret(key).strip()
    except Exception:
        if key != name:
            try:
                return get_secret(name).strip()
            except Exception:
                return None
        return None


def _verify_cloudflare_api(
    command: Callable[..., CommandResult] = run_command,
) -> tuple[str, str]:
    token = _secret_or_env("CLOUDFLARE_API_TOKEN")
    if not token:
        return "failed", "Cloudflare API token is not configured"
    account_id = _cloudflare_account_id()
    path = (
        f"/accounts/{account_id}/tokens/verify" if account_id else "/user/tokens/verify"
    )
    result = command(
        [
            "curl",
            "-sS",
            "--max-time",
            "20",
            "-H",
            f"Authorization: Bearer {token}",
            f"{CLOUDFLARE_API_BASE.rstrip()}{path}",
        ],
        timeout=25,
    )
    if result.returncode != 0:
        return "failed", "Cloudflare token verify request failed"
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return "failed", "Cloudflare token verify returned invalid JSON"
    if payload.get("success") is True:
        return "passed", "Cloudflare token verified"
    return "failed", json.dumps(payload.get("errors") or payload)[:240]


def _verify_github_api(
    token: str | None,
    expect_login: str | None,
    command: Callable[..., CommandResult] = run_command,
) -> tuple[str, str]:
    if not token:
        return "failed", "GitHub token is not configured"
    result = command(
        [
            "curl",
            "-sS",
            "--max-time",
            "20",
            "-H",
            f"Authorization: token {token}",
            "https://api.github.com/user",
        ],
        timeout=25,
    )
    if result.returncode != 0:
        return "failed", "GitHub token probe failed"
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return "failed", "GitHub token probe returned invalid JSON"
    login = str(payload.get("login") or "")
    if expect_login and login != expect_login:
        return "failed", "GitHub token login did not match expected account"
    return "passed", "GitHub token verified"


def _verify_latest_gmail_health(
    psql: Callable[[str], CommandResult] = run_psql,
    now: datetime | None = None,
) -> tuple[str, str]:
    now = now or datetime.now(UTC)
    query = """
SELECT status,
       COALESCE(checked_at::text, ''),
       COALESCE(error_type, ''),
       COALESCE(error_subtype, '')
FROM public.alpha_gmail_oauth_health
ORDER BY checked_at DESC
LIMIT 1;
""".strip()
    result = psql(query)
    if result.returncode != 0:
        return "failed", "Could not read Gmail OAuth health ledger"
    rows = parse_psql_rows(result.stdout)
    if not rows:
        return "warning", "No Gmail OAuth health check has been recorded"
    status, checked_at, error_type, error_subtype = (rows[0] + ["", "", "", ""])[:4]
    checked = _parse_timestamp(checked_at)
    if checked is None:
        return "warning", "Latest Gmail OAuth health timestamp is invalid"
    age_hours = (now - checked).total_seconds() / 3600
    if status != "ok":
        detail = " ".join(part for part in (error_type, error_subtype) if part)
        return "failed", f"Gmail OAuth health is {status}: {detail}".strip()
    if age_hours > SECRET_VERIFY_MAX_AGE_HOURS:
        return "warning", f"Gmail OAuth health is stale ({age_hours:.1f} hours old)"
    return "passed", f"Gmail OAuth health ok ({age_hours:.1f} hours old)"


def _verify_health_url(
    spec: dict[str, object],
    *,
    command: Callable[..., CommandResult] = run_command,
) -> tuple[str, str]:
    restarts = spec.get("restarts")
    if not isinstance(restarts, list):
        return "skipped", "no health URL configured"
    urls = [
        str(item.get("health_url"))
        for item in restarts
        if isinstance(item, dict) and item.get("health_url")
    ]
    if not urls:
        return "skipped", "no health URL configured"
    failures = []
    for url in urls:
        result = command(
            [
                "curl",
                "-sk",
                "--max-time",
                "15",
                "-o",
                "/dev/null",
                "-w",
                "%{http_code}",
                url,
            ],
            timeout=20,
        )
        code = (result.stdout or "").strip()
        if result.returncode != 0 or not code.startswith(("2", "3")):
            failures.append(f"{url} HTTP {code or result.returncode}")
    if failures:
        return "failed", "; ".join(failures[:3])
    return "passed", f"{len(urls)} health URL(s) reachable"


def _verify_family_smoke_auth(
    spec: dict[str, object],
    pin: str,
    *,
    member_name: str = "smoke_test_parent",
    expected_role: str = "parent",
    command: Callable[..., CommandResult] = run_command,
) -> tuple[str, str]:
    restarts = spec.get("restarts")
    if not isinstance(restarts, list):
        return "skipped", "no Family smoke auth URL configured"
    health_url = next(
        (
            str(item.get("health_url"))
            for item in restarts
            if isinstance(item, dict) and item.get("health_url")
        ),
        "",
    )
    if not health_url.endswith("/health"):
        return "skipped", "Family smoke auth URL could not be derived"
    auth_url = health_url[: -len("/health")] + "/v1/auth/pin"
    result = command(
        [
            "curl",
            "-sk",
            "--max-time",
            "20",
            "-X",
            "POST",
            "-H",
            "Content-Type: application/json",
            "-d",
            json.dumps({"name": member_name, "pin": pin}),
            auth_url,
        ],
        timeout=25,
    )
    if result.returncode != 0:
        return "failed", "Family smoke auth request failed"
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return "failed", "Family smoke auth returned invalid JSON"
    if payload.get("token") and payload.get("role") == expected_role:
        return "passed", f"Family smoke auth passed for synthetic {expected_role}"
    return (
        "failed",
        f"Family smoke auth did not return a synthetic {expected_role} token",
    )


def _verify_secret_live(
    name: str,
    spec: dict[str, object],
    *,
    node_map: dict[str, dict[str, str]],
    psql: Callable[[str], CommandResult] = run_psql,
    command: Callable[..., CommandResult] = run_command,
    ssh: Callable[[str, str], CommandResult] = run_ssh,
) -> tuple[str, str]:
    verify = spec.get("verify") if isinstance(spec.get("verify"), dict) else {}
    verify_type = str(verify.get("type") or "none")
    if verify_type == "none":
        return "skipped", "no live probe configured"
    if verify_type == "jwt_exp":
        nodes = spec.get("nodes") if isinstance(spec.get("nodes"), list) else []
        secret_key = str(spec.get("secret_key") or name)
        min_hours = float(verify.get("min_hours") or JWT_VERIFY_MIN_HOURS)
        local_node = current_node_name()
        if len(nodes) == 1 and nodes[0] != local_node:
            return _remote_jwt_verify(
                str(nodes[0]),
                secret_key,
                node_map,
                min_hours=min_hours,
                ssh=ssh,
            )
        token = _secret_value_for_probe(name, spec)
        if not token:
            return "failed", "JWT secret is not configured"
        return _verify_jwt_exp(token, min_hours=min_hours)
    if verify_type == "cloudflare_api":
        return _verify_cloudflare_api(command=command)
    if verify_type == "github_api":
        return _verify_github_api(
            _secret_value_for_probe(name, spec),
            str(verify.get("expect_login") or ""),
            command=command,
        )
    if verify_type == "gmail_oauth_health":
        return _verify_latest_gmail_health(psql=psql)
    if verify_type == "gateway_health":
        if not _secret_value_for_probe(name, spec):
            return "failed", "secret is not configured"
        return _verify_health_url(spec, command=command)
    if verify_type == "family_smoke":
        status, detail = _verify_health_url(spec, command=command)
        if status == "failed":
            return status, detail
        pin = _secret_value_for_probe(name, spec)
        if not pin:
            return (
                "warning",
                "Family smoke PIN is not available to Porchlight; API health is reachable",
            )
        return _verify_family_smoke_auth(spec, pin, command=command)
    if verify_type == "family_external_smoke":
        status, detail = _verify_health_url(spec, command=command)
        if status == "failed":
            return status, detail
        pin = _secret_value_for_probe(name, spec)
        if not pin:
            return (
                "warning",
                "Family external smoke PIN is not available to Porchlight; API health is reachable",
            )
        return _verify_family_smoke_auth(
            spec,
            pin,
            member_name="smoke_test_external",
            expected_role="external",
            command=command,
        )
    return "skipped", f"{verify_type} is side-effecting or not implemented"


def check_secret_live_verification(
    node_map: dict[str, dict[str, str]] | None = None,
    config_path: Path = SECRET_ROTATION_CONFIG,
    psql: Callable[[str], CommandResult] = run_psql,
    command: Callable[..., CommandResult] = run_command,
    ssh: Callable[[str, str], CommandResult] = run_ssh,
) -> CheckResult:
    node_map = node_map or load_json(NODE_MAP_PATH)
    config = load_json(config_path)
    configured = config.get("secrets", {})
    results: dict[str, dict[str, str]] = {}
    failed: list[str] = []
    warning: list[str] = []

    for name, raw_spec in configured.items():
        spec = raw_spec if isinstance(raw_spec, dict) else {}
        status, detail = _verify_secret_live(
            name,
            spec,
            node_map=node_map,
            psql=psql,
            command=command,
            ssh=ssh,
        )
        results[name] = {"status": status, "detail": detail}
        if status == "failed":
            failed.append(f"{name}: {detail}")
        elif status == "warning":
            warning.append(f"{name}: {detail}")

    verified_count = sum(1 for item in results.values() if item["status"] == "passed")
    skipped_count = sum(1 for item in results.values() if item["status"] == "skipped")
    if failed:
        return CheckResult(
            name="secret_live_verification",
            status="fail",
            severity="critical",
            summary="One or more managed secrets failed live verification.",
            detail="; ".join((failed + warning)[:10]),
            metadata={"results": results},
        )
    if warning:
        return CheckResult(
            name="secret_live_verification",
            status="warn",
            severity="medium",
            summary="One or more managed secrets need live-verification attention.",
            detail="; ".join(warning[:10]),
            metadata={"results": results},
        )
    return CheckResult(
        name="secret_live_verification",
        status="pass",
        severity="info",
        summary=(
            f"Live verification passed for {verified_count} managed secret(s); "
            f"{skipped_count} probe(s) are skipped by design."
        ),
        metadata={"results": results},
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


def _secret_or_env(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    if value:
        return value
    try:
        return get_secret(name).strip()
    except Exception:
        return None


def _cloudflare_expected_hosts() -> list[str]:
    configured = os.getenv("PORCHLIGHT_CLOUDFLARE_EXPECTED_HOSTS", "").strip()
    if configured:
        hosts = [item.strip().lower() for item in configured.split(",")]
        return sorted({host for host in hosts if host})
    host = urlparse(CLOUDFLARE_ACCESS_URL).hostname
    return [host.lower()] if host else []


def _cloudflare_expected_actors() -> set[str]:
    configured = os.getenv("PORCHLIGHT_CLOUDFLARE_EXPECTED_ACTORS", "").strip()
    if configured:
        return {item.strip().lower() for item in configured.split(",") if item.strip()}
    return set(DEFAULT_CLOUDFLARE_EXPECTED_ACTORS)


def _csv_env_set(name: str) -> set[str]:
    configured = os.getenv(name, "").strip()
    if not configured:
        return set()
    return {item.strip().lower() for item in configured.split(",") if item.strip()}


def _cloudflare_expected_policy_emails() -> set[str]:
    return _csv_env_set("PORCHLIGHT_CLOUDFLARE_EXPECTED_POLICY_EMAILS")


def _cloudflare_allowed_public_hosts() -> set[str]:
    return _csv_env_set("PORCHLIGHT_CLOUDFLARE_ALLOWED_PUBLIC_HOSTS")


def _cloudflare_forbidden_host_patterns() -> tuple[str, ...]:
    configured = os.getenv("PORCHLIGHT_CLOUDFLARE_FORBIDDEN_HOST_PATTERNS", "").strip()
    if configured:
        return tuple(
            item.strip().lower() for item in configured.split(",") if item.strip()
        )
    return DEFAULT_CLOUDFLARE_FORBIDDEN_HOST_PATTERNS


def _cloudflare_forbidden_app_terms() -> tuple[str, ...]:
    configured = os.getenv("PORCHLIGHT_CLOUDFLARE_FORBIDDEN_APP_TERMS", "").strip()
    if configured:
        return tuple(
            item.strip().lower() for item in configured.split(",") if item.strip()
        )
    return DEFAULT_CLOUDFLARE_FORBIDDEN_APP_TERMS


def _cloudflare_api_get(
    path: str,
    *,
    params: dict[str, str] | None = None,
    command: Callable[..., CommandResult] = run_command,
) -> tuple[int, dict]:
    token = _secret_or_env("CLOUDFLARE_API_TOKEN")
    if not token:
        return 0, {"success": False, "errors": [{"message": "missing_token"}]}
    query = f"?{urlencode(params)}" if params else ""
    result = command(
        [
            "curl",
            "-sS",
            "--max-time",
            "20",
            "-H",
            f"Authorization: Bearer {token}",
            f"{CLOUDFLARE_API_BASE.rstrip('/')}{path}{query}",
        ],
        timeout=25,
    )
    if result.returncode != 0:
        return result.returncode, {
            "success": False,
            "errors": [{"message": (result.stderr or result.stdout).strip()[:500]}],
        }
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return 1, {"success": False, "errors": [{"message": "invalid_json"}]}
    return 0, payload if isinstance(payload, dict) else {"success": False}


def _cloudflare_account_id() -> str | None:
    return _secret_or_env("CLOUDFLARE_ACCOUNT_ID")


def _app_hostnames(app: dict) -> set[str]:
    hosts = set()
    for key in ("domain", "aud", "hostname"):
        value = app.get(key)
        if isinstance(value, str) and value:
            host = value.split("/", 1)[0].lower()
            hosts.add(host)
    for nested_key in ("domains", "self_hosted_domains"):
        value = app.get(nested_key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item:
                    hosts.add(item.split("/", 1)[0].lower())
    return hosts


def _policy_has_everyone_rule(policy: dict) -> bool:
    for rule_key in ("include", "exclude", "require"):
        rules = policy.get(rule_key)
        if not isinstance(rules, list):
            continue
        for rule in rules:
            if isinstance(rule, dict) and "everyone" in rule:
                return True
    return False


def _policy_broad_rule_details(policy: dict) -> list[str]:
    details: list[str] = []
    for rule_key in ("include", "exclude", "require"):
        rules = policy.get(rule_key)
        if not isinstance(rules, list):
            continue
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            if "email_domain" in rule:
                details.append(f"{rule_key}: email_domain")
            if "everyone" in rule:
                details.append(f"{rule_key}: everyone")
            if "common_name" in rule:
                details.append(f"{rule_key}: common_name")
    return details


def _policy_email_values(policy: dict) -> set[str]:
    emails: set[str] = set()
    for rule_key in ("include", "require"):
        rules = policy.get(rule_key)
        if not isinstance(rules, list):
            continue
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            email_rule = rule.get("email")
            if isinstance(email_rule, dict):
                email = email_rule.get("email")
                if isinstance(email, str) and email.strip():
                    emails.add(email.strip().lower())
            if isinstance(email_rule, str) and email_rule.strip():
                emails.add(email_rule.strip().lower())
            emails_rule = rule.get("emails")
            if isinstance(emails_rule, list):
                emails.update(
                    item.strip().lower()
                    for item in emails_rule
                    if isinstance(item, str) and item.strip()
                )
    return emails


def _forbidden_cloudflare_apps(apps: list[dict]) -> list[str]:
    allowed_hosts = _cloudflare_allowed_public_hosts()
    host_patterns = _cloudflare_forbidden_host_patterns()
    app_terms = _cloudflare_forbidden_app_terms()
    forbidden: list[str] = []
    for app in apps:
        if not isinstance(app, dict):
            continue
        name = str(app.get("name") or app.get("id") or "unknown")
        name_lc = name.lower()
        hostnames = _app_hostnames(app)
        blocked_hosts = [
            host
            for host in sorted(hostnames)
            if host not in allowed_hosts
            and any(fnmatch(host, pattern) for pattern in host_patterns)
        ]
        term_hit = next((term for term in app_terms if term in name_lc), None)
        if blocked_hosts:
            forbidden.append(f"{name}: {', '.join(blocked_hosts)}")
        elif term_hit and not (hostnames and hostnames <= allowed_hosts):
            forbidden.append(f"{name}: app name contains {term_hit!r}")
    return forbidden


def check_cloudflare_access_policy_drift(
    command: Callable[..., CommandResult] = run_command,
) -> CheckResult:
    account_id = _cloudflare_account_id()
    expected_hosts = _cloudflare_expected_hosts()
    if not account_id or not _secret_or_env("CLOUDFLARE_API_TOKEN"):
        return CheckResult(
            name="cloudflare_access_policy_drift",
            status="warn",
            severity="medium",
            summary="Cloudflare API credentials are not configured for Access policy monitoring.",
            detail="Set CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN on Brain secrets.",
            metadata={"expected_hosts": expected_hosts},
        )

    rc, payload = _cloudflare_api_get(
        f"/accounts/{account_id}/access/apps",
        command=command,
    )
    if rc != 0 or payload.get("success") is not True:
        return CheckResult(
            name="cloudflare_access_policy_drift",
            status="fail",
            severity="high",
            summary="Could not list Cloudflare Access applications.",
            detail=json.dumps(payload.get("errors") or payload)[:500],
            metadata={"expected_hosts": expected_hosts},
        )

    apps = payload.get("result") if isinstance(payload.get("result"), list) else []
    forbidden_apps = _forbidden_cloudflare_apps(apps)
    if forbidden_apps:
        return CheckResult(
            name="cloudflare_access_policy_drift",
            status="fail",
            severity="critical",
            summary="Forbidden Alpha/Brain-style Cloudflare Access app exposure detected.",
            detail=", ".join(forbidden_apps[:8]),
            metadata={
                "expected_hosts": expected_hosts,
                "forbidden_apps": forbidden_apps,
                "allowed_public_hosts": sorted(_cloudflare_allowed_public_hosts()),
            },
        )

    matched = []
    risky_policies: list[str] = []
    no_policy_apps: list[str] = []
    expected_policy_emails = _cloudflare_expected_policy_emails()
    matched_policy_emails: set[str] = set()
    for app in apps:
        if not isinstance(app, dict):
            continue
        hostnames = _app_hostnames(app)
        if expected_hosts and not (hostnames & set(expected_hosts)):
            continue
        app_id = str(app.get("id") or "")
        name = str(app.get("name") or app_id or "unknown")
        matched.append({"id": app_id, "name": name, "hostnames": sorted(hostnames)})
        policies = app.get("policies")
        if not isinstance(policies, list) and app_id:
            _rc, policy_payload = _cloudflare_api_get(
                f"/accounts/{account_id}/access/apps/{app_id}/policies",
                command=command,
            )
            policies = (
                policy_payload.get("result")
                if isinstance(policy_payload.get("result"), list)
                else []
            )
        if not policies:
            no_policy_apps.append(name)
            continue
        for policy in policies:
            if not isinstance(policy, dict):
                continue
            matched_policy_emails.update(_policy_email_values(policy))
            action = str(policy.get("decision") or policy.get("action") or "").lower()
            policy_name = str(policy.get("name") or policy.get("id") or "unknown")
            if action == "bypass":
                risky_policies.append(f"{name}.{policy_name}: bypass")
            for detail in _policy_broad_rule_details(policy):
                risky_policies.append(f"{name}.{policy_name}: {detail}")

    if expected_hosts and not matched:
        return CheckResult(
            name="cloudflare_access_policy_drift",
            status="fail",
            severity="critical",
            summary="No Cloudflare Access application matched the expected protected hostnames.",
            detail=", ".join(expected_hosts),
            metadata={"expected_hosts": expected_hosts, "apps_seen": len(apps)},
        )
    if risky_policies or no_policy_apps:
        details = []
        if risky_policies:
            details.append("risky policies: " + ", ".join(risky_policies[:8]))
        if no_policy_apps:
            details.append("apps without policies: " + ", ".join(no_policy_apps[:8]))
        return CheckResult(
            name="cloudflare_access_policy_drift",
            status="fail",
            severity="critical",
            summary="Cloudflare Access policy drift needs review.",
            detail="; ".join(details),
            metadata={
                "expected_hosts": expected_hosts,
                "matched": matched,
                "risky_policies": risky_policies,
                "no_policy_apps": no_policy_apps,
            },
        )
    if expected_policy_emails:
        missing = sorted(expected_policy_emails - matched_policy_emails)
        unexpected = sorted(matched_policy_emails - expected_policy_emails)
        if missing or unexpected:
            details = []
            if missing:
                details.append("missing expected email(s): " + ", ".join(missing[:8]))
            if unexpected:
                details.append("unexpected email(s): " + ", ".join(unexpected[:8]))
            return CheckResult(
                name="cloudflare_access_policy_drift",
                status="fail",
                severity="critical",
                summary="Cloudflare Access policy membership drift needs review.",
                detail="; ".join(details),
                metadata={
                    "expected_hosts": expected_hosts,
                    "expected_policy_emails_count": len(expected_policy_emails),
                    "matched_policy_emails_count": len(matched_policy_emails),
                    "missing_policy_emails": missing,
                    "unexpected_policy_emails": unexpected,
                },
            )

    return CheckResult(
        name="cloudflare_access_policy_drift",
        status="pass",
        severity="info",
        summary=f"Cloudflare Access policy shape is safe for {len(matched)} protected app(s).",
        metadata={
            "expected_hosts": expected_hosts,
            "matched": matched,
            "expected_policy_emails_count": len(expected_policy_emails),
            "matched_policy_emails_count": len(matched_policy_emails),
        },
    )


def check_cloudflare_audit_logs(
    command: Callable[..., CommandResult] = run_command,
    now: datetime | None = None,
    window_hours: int = 24,
) -> CheckResult:
    account_id = _cloudflare_account_id()
    if not account_id or not _secret_or_env("CLOUDFLARE_API_TOKEN"):
        return CheckResult(
            name="cloudflare_audit_logs",
            status="warn",
            severity="medium",
            summary="Cloudflare audit-log monitoring is not configured.",
            detail="Set CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN on Brain secrets.",
        )

    now = now or datetime.now(UTC)
    since = (now - timedelta(hours=window_hours)).isoformat().replace("+00:00", "Z")
    before = now.isoformat().replace("+00:00", "Z")
    rc, payload = _cloudflare_api_get(
        f"/accounts/{account_id}/logs/audit",
        params={"since": since, "before": before, "per_page": "100"},
        command=command,
    )
    if rc != 0 or payload.get("success") is not True:
        return CheckResult(
            name="cloudflare_audit_logs",
            status="fail",
            severity="high",
            summary="Could not retrieve Cloudflare account audit logs.",
            detail=json.dumps(payload.get("errors") or payload)[:500],
        )

    logs = payload.get("result") if isinstance(payload.get("result"), list) else []
    access_related: list[dict[str, str]] = []
    expected_changes: list[dict[str, str]] = []
    unexpected_changes: list[str] = []
    failures: list[str] = []
    expected_actors = _cloudflare_expected_actors()
    for entry in logs:
        if not isinstance(entry, dict):
            continue
        haystack = json.dumps(entry, sort_keys=True, default=str).lower()
        if not any(term in haystack for term in ("access", "zero trust", "tunnel")):
            continue
        action = entry.get("action") if isinstance(entry.get("action"), dict) else {}
        actor = entry.get("actor") if isinstance(entry.get("actor"), dict) else {}
        resource = (
            entry.get("resource") if isinstance(entry.get("resource"), dict) else {}
        )
        item = {
            "when": str(entry.get("when") or ""),
            "actor": str(actor.get("email") or actor.get("id") or "unknown"),
            "action": str(action.get("type") or "unknown"),
            "result": str(action.get("result")),
            "resource": str(resource.get("type") or resource.get("id") or "unknown"),
        }
        access_related.append(item)
        if action.get("result") is False:
            failures.append(f"{item['when']} {item['actor']} {item['action']}")
            continue
        if item["actor"].lower() in expected_actors:
            expected_changes.append(item)
        else:
            unexpected_changes.append(
                f"{item['when']} {item['actor']} {item['action']}"
            )

    if failures:
        return CheckResult(
            name="cloudflare_audit_logs",
            status="fail",
            severity="high",
            summary="Cloudflare Access/Zero Trust audit logs contain failed control-plane actions.",
            detail="; ".join(failures[:8]),
            metadata={"window_hours": window_hours, "events": access_related[:20]},
        )
    if unexpected_changes:
        return CheckResult(
            name="cloudflare_audit_logs",
            status="warn",
            severity="medium",
            summary="Unexpected Cloudflare Access/Zero Trust changes occurred within the audit window.",
            detail="; ".join(unexpected_changes[:8]),
            metadata={
                "window_hours": window_hours,
                "events": access_related[:20],
                "expected_actors": sorted(expected_actors),
            },
        )
    if expected_changes:
        return CheckResult(
            name="cloudflare_audit_logs",
            status="pass",
            severity="info",
            summary="Only expected Cloudflare Access/Zero Trust changes occurred within the audit window.",
            detail="; ".join(
                f"{item['when']} {item['actor']} {item['action']}"
                for item in expected_changes[:8]
            ),
            metadata={
                "window_hours": window_hours,
                "events": access_related[:20],
                "expected_actors": sorted(expected_actors),
            },
        )

    return CheckResult(
        name="cloudflare_audit_logs",
        status="pass",
        severity="info",
        summary=f"No Cloudflare Access/Zero Trust audit-log changes in {window_hours} hours.",
        metadata={"window_hours": window_hours, "events_checked": len(logs)},
    )


def _severity_counts() -> dict[str, int]:
    return {"critical": 0, "high": 0, "medium": 0, "low": 0, "unknown": 0}


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _pip_audit_counts(payload: dict) -> dict[str, int]:
    counts = _severity_counts()
    for dependency in payload.get("dependencies") or []:
        if not isinstance(dependency, dict):
            continue
        for vuln in dependency.get("vulns") or []:
            if not isinstance(vuln, dict):
                continue
            aliases = [str(item).lower() for item in vuln.get("aliases") or []]
            severity = str(vuln.get("severity") or "").lower()
            if severity not in counts:
                if any(item.startswith("ghsa-") for item in aliases):
                    severity = "unknown"
                else:
                    severity = "unknown"
            counts[severity] += 1
    return counts


def _npm_audit_counts(payload: dict) -> dict[str, int]:
    counts = _severity_counts()
    vulnerabilities = payload.get("vulnerabilities")
    if isinstance(vulnerabilities, dict):
        for item in vulnerabilities.values():
            if not isinstance(item, dict):
                continue
            severity = str(item.get("severity") or "unknown").lower()
            counts[severity if severity in counts else "unknown"] += 1
        return counts

    metadata = (
        payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    )
    vuln_meta = metadata.get("vulnerabilities")
    if isinstance(vuln_meta, dict):
        for severity in counts:
            value = vuln_meta.get(severity)
            if isinstance(value, int):
                counts[severity] += value
    return counts


def _merge_counts(items: list[dict[str, int]]) -> dict[str, int]:
    merged = _severity_counts()
    for item in items:
        for severity in merged:
            merged[severity] += int(item.get(severity) or 0)
    return merged


def _npm_audit_env() -> dict[str, str]:
    env = {**os.environ, "npm_config_audit_level": "low"}
    npm_path = Path(NPM_BIN)
    if npm_path.is_absolute():
        path = env.get("PATH", "")
        env["PATH"] = f"{npm_path.parent}:{path}" if path else str(npm_path.parent)
    return env


def check_dependency_cve_scan(
    command: Callable[..., CommandResult] = run_command,
) -> CheckResult:
    """Summarize Python/npm dependency vulnerability scanners without blocking if absent."""
    scanner_results: list[dict[str, object]] = []
    counts: list[dict[str, int]] = []
    scanners_attempted = 0
    scanners_available = 0

    for requirements in PYTHON_REQUIREMENTS:
        if not requirements.exists():
            continue
        scanners_attempted += 1
        result = command(
            [
                sys.executable,
                "-m",
                "pip_audit",
                "-r",
                str(requirements),
                "-f",
                "json",
            ],
            timeout=120,
        )
        if not result.stdout.strip():
            scanner_results.append(
                {
                    "scanner": "pip-audit",
                    "target": _display_path(requirements),
                    "available": False,
                    "error": (result.stderr or "no output").strip()[:300],
                }
            )
            continue
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            scanner_results.append(
                {
                    "scanner": "pip-audit",
                    "target": _display_path(requirements),
                    "available": False,
                    "error": "invalid_json",
                }
            )
            continue
        scanners_available += 1
        item_counts = _pip_audit_counts(payload)
        counts.append(item_counts)
        scanner_results.append(
            {
                "scanner": "pip-audit",
                "target": _display_path(requirements),
                "available": True,
                "counts": item_counts,
            }
        )

    if (UI_DIR / "package-lock.json").exists() or (
        UI_DIR / "npm-shrinkwrap.json"
    ).exists():
        scanners_attempted += 1
        result = command(
            [NPM_BIN, "audit", "--json", "--omit=dev"],
            timeout=120,
            env=_npm_audit_env(),
        )
        if not result.stdout.strip():
            scanner_results.append(
                {
                    "scanner": "npm-audit",
                    "target": "ui",
                    "available": False,
                    "error": (result.stderr or "no output").strip()[:300],
                }
            )
        else:
            try:
                payload = json.loads(result.stdout)
            except json.JSONDecodeError:
                scanner_results.append(
                    {
                        "scanner": "npm-audit",
                        "target": "ui",
                        "available": False,
                        "error": "invalid_json",
                    }
                )
            else:
                scanners_available += 1
                item_counts = _npm_audit_counts(payload)
                counts.append(item_counts)
                scanner_results.append(
                    {
                        "scanner": "npm-audit",
                        "target": "ui",
                        "available": True,
                        "counts": item_counts,
                    }
                )

    total = _merge_counts(counts)
    metadata = {
        "scanners_attempted": scanners_attempted,
        "scanners_available": scanners_available,
        "counts": total,
        "scanners": scanner_results,
    }
    critical_high = total["critical"] + total["high"]
    medium = total["medium"]
    if critical_high:
        return CheckResult(
            name="dependency_cve_scan",
            status="fail",
            severity="high",
            summary="Dependency vulnerability scanners found high or critical CVEs.",
            detail=f"{total['critical']} critical, {total['high']} high, {medium} medium",
            metadata=metadata,
        )
    if medium:
        return CheckResult(
            name="dependency_cve_scan",
            status="warn",
            severity="medium",
            summary="Dependency vulnerability scanners found medium CVEs.",
            detail=f"{medium} medium, {total['low']} low, {total['unknown']} unknown",
            metadata=metadata,
        )
    if scanners_attempted and scanners_available == 0:
        return CheckResult(
            name="dependency_cve_scan",
            status="warn",
            severity="medium",
            summary="Dependency vulnerability scan could not run on this node.",
            detail="Install pip-audit and ensure npm is available for full Porchlight coverage.",
            metadata=metadata,
        )
    return CheckResult(
        name="dependency_cve_scan",
        status="pass",
        severity="info",
        summary="Dependency vulnerability scanners reported no medium-or-higher CVEs.",
        metadata=metadata,
    )


def _github_branch_protection_repos() -> list[str]:
    configured = os.getenv("PORCHLIGHT_GITHUB_BRANCH_PROTECTION_REPOS", "").strip()
    if configured:
        repos = [item.strip() for item in configured.split(",")]
        return sorted({repo for repo in repos if repo})
    return list(DEFAULT_GITHUB_BRANCH_PROTECTION_REPOS)


def _github_required_checks() -> set[str]:
    configured = os.getenv("PORCHLIGHT_GITHUB_REQUIRED_CHECKS", "").strip()
    if not configured:
        return set()
    return {item.strip() for item in configured.split(",") if item.strip()}


def _github_api_get(
    path: str,
    *,
    command: Callable[..., CommandResult] = run_command,
) -> tuple[int, dict]:
    token = _secret_or_env("GITHUB_TOKEN")
    if not token:
        return 0, {"message": "missing_token"}
    result = command(
        [
            "curl",
            "-sS",
            "--max-time",
            "20",
            "-H",
            "Accept: application/vnd.github+json",
            "-H",
            f"Authorization: Bearer {token}",
            f"https://api.github.com{path}",
        ],
        timeout=25,
    )
    if result.returncode != 0:
        return result.returncode, {
            "message": (result.stderr or result.stdout).strip()[:500]
        }
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return 1, {"message": "invalid_json"}
    return 0, payload if isinstance(payload, dict) else {"message": "invalid_json"}


def _status_check_contexts(protection: dict) -> set[str]:
    checks = protection.get("required_status_checks")
    if not isinstance(checks, dict):
        return set()
    contexts = set()
    raw_contexts = checks.get("contexts")
    if isinstance(raw_contexts, list):
        contexts.update(str(item) for item in raw_contexts if item)
    raw_checks = checks.get("checks")
    if isinstance(raw_checks, list):
        for item in raw_checks:
            if isinstance(item, dict) and item.get("context"):
                contexts.add(str(item["context"]))
    return contexts


def check_github_branch_protection_drift(
    command: Callable[..., CommandResult] = run_command,
) -> CheckResult:
    repos = _github_branch_protection_repos()
    branch = os.getenv("PORCHLIGHT_GITHUB_BRANCH", "main").strip() or "main"
    required_checks = _github_required_checks()
    if not _secret_or_env("GITHUB_TOKEN"):
        return CheckResult(
            name="github_branch_protection_drift",
            status="warn",
            severity="medium",
            summary="GitHub API token is not configured for branch-protection monitoring.",
            detail="Set GITHUB_TOKEN on Brain secrets.",
            metadata={"repos": repos, "branch": branch},
        )

    findings: list[str] = []
    warnings: list[str] = []
    repo_results: list[dict[str, object]] = []
    for repo in repos:
        rc, payload = _github_api_get(
            f"/repos/{repo}/branches/{branch}/protection",
            command=command,
        )
        if rc != 0 or payload.get("message") in {
            "Not Found",
            "missing_token",
            "invalid_json",
        }:
            findings.append(f"{repo}:{branch} protection unavailable")
            repo_results.append(
                {
                    "repo": repo,
                    "branch": branch,
                    "status": "unavailable",
                    "message": payload.get("message"),
                }
            )
            continue
        contexts = _status_check_contexts(payload)
        missing_checks = sorted(required_checks - contexts)
        has_reviews = isinstance(payload.get("required_pull_request_reviews"), dict)
        has_status_checks = isinstance(payload.get("required_status_checks"), dict)
        if not has_reviews:
            findings.append(f"{repo}:{branch} missing PR-review requirement")
        if required_checks and missing_checks:
            findings.append(
                f"{repo}:{branch} missing required checks: {', '.join(missing_checks)}"
            )
        elif not has_status_checks:
            warnings.append(f"{repo}:{branch} has no required status checks")
        repo_results.append(
            {
                "repo": repo,
                "branch": branch,
                "status": "checked",
                "has_pr_reviews": has_reviews,
                "has_status_checks": has_status_checks,
                "required_checks": sorted(required_checks),
                "contexts": sorted(contexts),
            }
        )

    metadata = {
        "repos": repo_results,
        "branch": branch,
        "required_checks": sorted(required_checks),
    }
    if findings:
        return CheckResult(
            name="github_branch_protection_drift",
            status="fail",
            severity="high",
            summary="GitHub branch protection drift needs remediation.",
            detail="; ".join(findings[:8]),
            metadata=metadata,
        )
    if warnings:
        return CheckResult(
            name="github_branch_protection_drift",
            status="warn",
            severity="medium",
            summary="GitHub branch protection is enabled but has weaker-than-target controls.",
            detail="; ".join(warnings[:8]),
            metadata=metadata,
        )
    return CheckResult(
        name="github_branch_protection_drift",
        status="pass",
        severity="info",
        summary=f"GitHub branch protection is present for {len(repos)} repo(s).",
        metadata=metadata,
    )


def check_route_db_access(
    routes_dir: Path = ROUTES_DIR,
    reviewed: dict[str, str] = REVIEWED_ROUTE_DB_ACCESS,
) -> CheckResult:
    raw_access: dict[str, int] = {}
    uses_rls_helper: list[str] = []
    for path in sorted(routes_dir.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        count = (
            text.count("pool.acquire(")
            + text.count("asyncpg.connect(")
            + text.count("create_pool(")
        )
        if count:
            raw_access[path.name] = count
        if "rls_connection(" in text or "platform_admin_connection(" in text:
            uses_rls_helper.append(path.name)

    unreviewed = sorted(set(raw_access) - set(reviewed))
    stale_reviews = sorted(set(reviewed) - set(raw_access))
    metadata = {
        "raw_route_files": raw_access,
        "reviewed": reviewed,
        "uses_rls_helper": uses_rls_helper,
        "unreviewed": unreviewed,
        "stale_reviews": stale_reviews,
    }

    if unreviewed:
        return CheckResult(
            name="route_db_access_review",
            status="fail",
            severity="high",
            summary="One or more route modules use direct DB access without a reviewed RLS rationale.",
            detail=", ".join(unreviewed),
            metadata=metadata,
        )

    if stale_reviews:
        return CheckResult(
            name="route_db_access_review",
            status="warn",
            severity="low",
            summary="Route DB access allowlist has stale entries to clean up.",
            detail=", ".join(stale_reviews),
            metadata=metadata,
        )

    return CheckResult(
        name="route_db_access_review",
        status="pass",
        severity="info",
        summary=f"{len(raw_access)} route modules with direct DB access have reviewed RLS rationales.",
        metadata=metadata,
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


ROUTINE_WARNING_CHECKS = {
    "secret_rotation",
}


def has_notifiable_security_condition(report: dict[str, object]) -> bool:
    for raw_check in report.get("checks", []):
        if not isinstance(raw_check, dict):
            continue
        status = raw_check.get("status")
        severity = str(raw_check.get("severity") or "info")
        name = str(raw_check.get("name") or "")
        if status == "fail":
            return True
        if status != "warn":
            continue
        if SEVERITY_RANK.get(severity, 0) >= SEVERITY_RANK["high"]:
            return True
        if name not in ROUTINE_WARNING_CHECKS:
            return True
    return False


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
            "-sS",
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
        check_postgres_role_safety(),
        check_postgres_hba_safety(),
        check_secret_rotation(),
        check_secret_live_verification(node_map=node_map),
        check_security_launchagents(node_map=node_map),
        check_token_rotation_logs(
            node_map=node_map,
            max_age_hours=args.max_token_log_age_hours,
        ),
        check_cloudflare_access(args.cloudflare_access_url),
        check_cloudflare_access_policy_drift(),
        check_cloudflare_audit_logs(window_hours=args.cloudflare_audit_window_hours),
        check_dependency_cve_scan(),
        check_github_branch_protection_drift(),
        check_route_db_access(),
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
    parser.add_argument(
        "--cloudflare-audit-window-hours",
        type=int,
        default=24,
        help="Cloudflare audit-log lookback window in hours",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_sweep(args)
    write_report(report)

    should_post = args.always_report or (
        (report["status"] == "fail" or args.report_warnings)
        and has_notifiable_security_condition(report)
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
