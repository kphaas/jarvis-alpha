"""Security dashboard API — JWT check, RLS status, child profiles, perimeter."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field, ValidationError

from jarvis_common.secrets import get_secret
from jarvis_common.logging_config import get_logger
from brain.agents.events import AgentEvent, emit_agent_event
from brain.db.pool import get_pool
from brain.config.node_addresses import (
    BRAIN_URL,
    GATEWAY_URL,
    ENDPOINT_URL,
    SANDBOX_URL,
)
from brain.routes.pin_auth import _profile_scopes
from brain.agents.warden import (
    auto_ticket_candidates,
    owner_routes,
    weekly_security_brief,
)
from brain.services.warden_posture import (
    build_trade_guard_financial_evidence,
    build_warden_posture_score,
)

logger = get_logger("alpha_brain")
security_router = APIRouter(prefix="/v1/security", tags=["security"])

_PSQL = "/opt/homebrew/Cellar/postgresql@16/16.13/bin/psql"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_PORCHLIGHT_REPORT_PATH = Path(
    os.getenv(
        "PORCHLIGHT_REPORT_PATH",
        str(_REPO_ROOT / "logs" / "porchlight_security_report.json"),
    )
)
_CHILD_SENSITIVE_TABLES = (
    "alpha_profiles",
    "chat_threads",
    "chat_messages",
    "alpha_conversation_memory",
    "alpha_semantic_memory",
    "alpha_message_body_vault",
    "vault_documents",
    "alpha_dream_sessions",
    "alpha_task_graphs",
)
_LEGACY_CHILD_POLICIES = (
    "child_memory_rating",
    "child_memory_write",
    "child_dream_isolation",
    "child_dream_step_isolation",
    "child_task_isolation",
    "child_content_rating",
    "child_message_isolation",
    "child_thread_isolation",
)
SECURITY_MANAGED_AGENT_IDS = (
    "warden",
    "porchlight",
    "keyturner",
    "sweep",
    "tripwire",
    "ledger",
    "sentry",
    "trade_guard",
)
SWEEP_REPORT_SECRET_NAME = "ALPHA_SWEEP_REPORT_SECRET"
SWEEP_REPORT_MAX_SKEW_SECONDS = 300
SWEEP_REPORT_STALE_AFTER = timedelta(hours=24)
SWEEP_REPORT_EXPECTED_NODES = ("brain", "endpoint", "gateway", "sandbox")
PORCHLIGHT_REQUIRED_CHECKS = (
    "database_rls",
    "postgres_role_safety",
    "postgres_hba_safety",
    "secret_rotation",
    "secret_live_verification",
    "security_launchagents",
    "token_rotation_logs",
    "backup_recovery",
    "cloudflare_access",
    "cloudflare_access_policy_drift",
    "cloudflare_audit_logs",
    "dependency_cve_scan",
    "malware_scan_repo_freshness",
    "code_malware_scan",
    "secrets_leakage_scan",
    "outbound_egress_drift",
    "host_integrity",
    "runtime_exposure",
    "tailscale_ssh_posture",
    "sweep_tls_report_intake",
    "financial_security_posture",
    "github_branch_protection_drift",
    "route_db_access_review",
)
PORCHLIGHT_COMPLETENESS_CHECK = "porchlight_report_completeness"
_SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


class SentinelReportFinding(BaseModel):
    id: str = Field(min_length=1, max_length=96)
    severity: str = Field(pattern=r"^(critical|high|medium|low|info)$")
    title: str = Field(min_length=1, max_length=250)
    file_path: str | None = Field(default=None, max_length=500)
    start_line: int | None = Field(default=None, ge=1)


class SentinelReportIn(BaseModel):
    repo_slug: str = Field(min_length=1, max_length=160)
    commit_sha: str = Field(min_length=1, max_length=80)
    branch: str | None = Field(default=None, max_length=160)
    scan_id: str = Field(min_length=1, max_length=128)
    scanner: str = Field(default="aider-security-review", min_length=1, max_length=96)
    findings_total: int = Field(ge=0)
    severity_counts: dict[str, int] = Field(default_factory=dict)
    finding_ids: list[str] = Field(default_factory=list, max_length=100)
    top_findings: list[SentinelReportFinding] = Field(
        default_factory=list, max_length=10
    )


class SentinelReportResponse(BaseModel):
    accepted: bool
    event_id: str
    notification_status: str


class SweepReportIn(BaseModel):
    node: Literal["brain", "endpoint", "gateway", "sandbox"]
    fqdn: str = Field(min_length=1, max_length=160)
    status: str = Field(min_length=1, max_length=48)
    days_remaining: int | None = None
    cert_issued_at: str | None = Field(default=None, max_length=80)
    cert_expires_at: str | None = Field(default=None, max_length=80)
    source_cert: str = Field(min_length=1, max_length=500)
    renewed: bool = False
    restarted: bool = False
    health_ok: bool | None = None
    error: str | None = Field(default=None, max_length=500)
    threshold_days: int = Field(default=30, ge=1, le=365)
    reported_at: str | None = Field(default=None, max_length=80)


class SweepReportResponse(BaseModel):
    accepted: bool
    event_id: str
    notification_status: str
    severity: str


class SecurityAgentEventOut(BaseModel):
    id: str
    agent_id: str
    run_id: str | None = None
    event_type: str
    severity: str
    title: str
    message: str
    correlation_id: str | None = None
    channel_key: str
    notification_status: str
    notification_error: str | None = None
    payload: dict = Field(default_factory=dict)
    notification_result: dict = Field(default_factory=dict)
    created_at: str
    notified_at: str | None = None


class SecurityAgentEventsResponse(BaseModel):
    count: int
    events: list[SecurityAgentEventOut]


def _jsonb(value) -> dict:
    if value is None:
        return {}
    if isinstance(value, str):
        return json.loads(value)
    return dict(value)


def _iso(value) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _security_agent_event_from_row(row) -> SecurityAgentEventOut:
    return SecurityAgentEventOut(
        id=str(row["id"]),
        agent_id=row["agent_id"],
        run_id=str(row["run_id"]) if row["run_id"] else None,
        event_type=row["event_type"],
        severity=row["severity"],
        title=row["title"],
        message=row["message"],
        correlation_id=row["correlation_id"],
        channel_key=row["channel_key"],
        notification_status=row["notification_status"],
        notification_error=row["notification_error"],
        payload=_jsonb(row["payload"]),
        notification_result=_jsonb(row["notification_result"]),
        created_at=_iso(row["created_at"]) or "",
        notified_at=_iso(row["notified_at"]),
    )


def _sentinel_event_severity(counts: dict[str, int]) -> str:
    if int(counts.get("critical", 0)) > 0:
        return "critical"
    if int(counts.get("high", 0)) > 0:
        return "error"
    if int(counts.get("medium", 0)) > 0:
        return "warning"
    return "info"


def _sentinel_event_message(report: SentinelReportIn) -> str:
    counts = report.severity_counts
    return (
        f"Sentinel scanned `{report.repo_slug}` at `{report.commit_sha[:12]}` and found "
        f"{report.findings_total} finding(s): "
        f"{int(counts.get('critical', 0))} critical, "
        f"{int(counts.get('high', 0))} high, "
        f"{int(counts.get('medium', 0))} medium."
    )


def _sweep_report_signature(secret: str, timestamp: str, body: bytes) -> str:
    message = timestamp.encode("utf-8") + b"." + body
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def _verify_sweep_report_signature(request: Request, body: bytes) -> str:
    timestamp = request.headers.get("X-Jarvis-Timestamp", "").strip()
    signature = request.headers.get("X-Jarvis-Signature", "").strip()
    node = request.headers.get("X-Jarvis-Node", "").strip().lower()
    if not timestamp or not signature or not node:
        raise HTTPException(status_code=401, detail="missing_sweep_report_signature")
    try:
        timestamp_value = int(timestamp)
    except ValueError as exc:
        raise HTTPException(
            status_code=401, detail="invalid_sweep_report_timestamp"
        ) from exc
    if abs(int(time.time()) - timestamp_value) > SWEEP_REPORT_MAX_SKEW_SECONDS:
        raise HTTPException(status_code=401, detail="stale_sweep_report_signature")
    try:
        secret = get_secret(SWEEP_REPORT_SECRET_NAME).strip()
    except KeyError as exc:
        raise HTTPException(
            status_code=503, detail="sweep_report_secret_missing"
        ) from exc
    expected = _sweep_report_signature(secret, timestamp, body)
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="invalid_sweep_report_signature")
    return node


def _sweep_report_severity(report: SweepReportIn) -> str:
    if report.status == "error" or report.health_ok is False:
        return "error"
    if (
        report.days_remaining is not None
        and report.days_remaining <= report.threshold_days
        and report.status not in {"renewed", "renewal_pending"}
    ):
        return "warning"
    return "info"


def _sweep_report_message(report: SweepReportIn) -> str:
    days = (
        f"{report.days_remaining} day(s) remaining"
        if report.days_remaining is not None
        else "days remaining unavailable"
    )
    health = (
        "health ok"
        if report.health_ok is True
        else "health failed"
        if report.health_ok is False
        else "health not checked"
    )
    detail = f"Sweep reported `{report.node}` certificate status `{report.status}`: {days}; {health}."
    if report.error:
        detail += f" Detail: {report.error[:240]}"
    return detail


def _sweep_report_event_payload(report: SweepReportIn) -> dict:
    return {
        "source": "node_local_sweep",
        "node": report.node,
        "fqdn": report.fqdn,
        "status": report.status,
        "days_remaining": report.days_remaining,
        "cert_issued_at": report.cert_issued_at,
        "cert_expires_at": report.cert_expires_at,
        "renewed": report.renewed,
        "restarted": report.restarted,
        "health_ok": report.health_ok,
        "threshold_days": report.threshold_days,
        "reported_at": report.reported_at,
        "error": report.error,
    }


def _sweep_latest_report_from_row(row, *, now: datetime) -> dict:
    payload = _jsonb(row["payload"])
    created_at = row["created_at"]
    age_seconds = (
        int((now - created_at).total_seconds())
        if hasattr(created_at, "tzinfo")
        else None
    )
    is_stale = age_seconds is None or age_seconds > int(
        SWEEP_REPORT_STALE_AFTER.total_seconds()
    )
    return {
        "node": payload.get("node"),
        "fqdn": payload.get("fqdn"),
        "status": payload.get("status"),
        "days_remaining": payload.get("days_remaining"),
        "cert_expires_at": payload.get("cert_expires_at"),
        "health_ok": payload.get("health_ok"),
        "threshold_days": payload.get("threshold_days"),
        "severity": row["severity"],
        "title": row["title"],
        "message": row["message"],
        "reported_at": payload.get("reported_at"),
        "received_at": _iso(created_at),
        "age_seconds": age_seconds,
        "is_stale": is_stale,
        "notification_status": row["notification_status"],
    }


def _sweep_report_summary(rows, *, now: datetime) -> dict:
    reports_by_node = {
        str(row["node"]): _sweep_latest_report_from_row(row, now=now) for row in rows
    }
    reports = []
    for node in SWEEP_REPORT_EXPECTED_NODES:
        reports.append(
            reports_by_node.get(
                node,
                {
                    "node": node,
                    "status": "missing",
                    "severity": "warning",
                    "message": "No node-local Sweep report has been received.",
                    "received_at": None,
                    "age_seconds": None,
                    "is_stale": True,
                    "notification_status": "not_sent",
                },
            )
        )
    attention = sum(
        1
        for report in reports
        if report["is_stale"]
        or report.get("severity") in {"warning", "error", "critical"}
        or report.get("health_ok") is False
    )
    return {
        "source": "alpha_agent_events",
        "expected_nodes": list(SWEEP_REPORT_EXPECTED_NODES),
        "stale_after_seconds": int(SWEEP_REPORT_STALE_AFTER.total_seconds()),
        "received": sum(1 for report in reports if report.get("received_at")),
        "attention": attention,
        "reports": reports,
    }


def _curl_http_code(
    url: str,
    method: str = "GET",
    max_time: str = "5",
    json_body: str | None = None,
) -> int:
    cmd = [
        "curl",
        "-sS",
        "--max-time",
        max_time,
        "-o",
        "/dev/null",
        "-w",
        "%{http_code}",
    ]
    if method.upper() == "POST":
        cmd.append("-X")
        cmd.append("POST")
        if json_body is not None:
            cmd.extend(["-H", "Content-Type: application/json", "-d", json_body])
    cmd.append(url)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        s = (r.stdout or "").strip()
        if s.isdigit():
            return int(s)
        return 0
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.debug("curl probe failed: %s", e)
        return 0


def _run_psql_rls_sync() -> str:
    query = """
SELECT c.relname,
       c.relrowsecurity::text,
       c.relforcerowsecurity::text,
       COALESCE(p.policy_count, 0)::text,
       COALESCE(p.policy_names, '') AS policy_names
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN (
    SELECT polrelid,
           COUNT(*) AS policy_count,
           string_agg(polname::text, ',' ORDER BY polname::text) AS policy_names
    FROM pg_policy
    GROUP BY polrelid
) p ON p.polrelid = c.oid
WHERE n.nspname = 'public'
  AND c.relkind = 'r'
  AND c.relname NOT IN ('schema_migrations')
ORDER BY c.relname;
"""
    env = os.environ.copy()
    try:
        password = (
            os.getenv("POSTGRES_PASSWORD") or get_secret("POSTGRES_PASSWORD")
        ).strip()
    except Exception as exc:  # pragma: no cover - defensive logging only
        password = ""
        logger.warning("POSTGRES_PASSWORD unavailable for rls-status: %s", exc)
    if password:
        env["PGPASSWORD"] = password
    r = subprocess.run(
        [
            _PSQL,
            "-h",
            "localhost",
            "-U",
            "jarvisbrain",
            "-d",
            "jarvis_alpha",
            "-t",
            "-A",
            "-F",
            "|",
            "-c",
            query.strip(),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    if r.returncode != 0:
        logger.warning("psql rls-status failed: %s", (r.stderr or "").strip())
    return r.stdout or ""


def _tailscale_status_sync() -> tuple[bool, int]:
    try:
        r = subprocess.run(
            ["/opt/homebrew/bin/tailscale", "status", "--json"],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if r.returncode != 0 or not (r.stdout or "").strip():
            return False, 0
        data = json.loads(r.stdout)
        peers = data.get("Peer") or {}
        if isinstance(peers, dict):
            n = 1 + len(peers)
        else:
            n = 1
        return True, n
    except (json.JSONDecodeError, OSError, subprocess.TimeoutExpired) as e:
        logger.debug("tailscale status failed: %s", e)
        return False, 0


def _host_from_service_url(url: str) -> str:
    return urlparse(url).hostname or "localhost"


def _load_porchlight_report() -> dict:
    if not _PORCHLIGHT_REPORT_PATH.exists():
        raise HTTPException(
            status_code=404,
            detail="Porchlight report has not been generated yet.",
        )
    try:
        report = json.loads(_PORCHLIGHT_REPORT_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=502,
            detail="Porchlight report is not valid JSON.",
        ) from exc
    if not isinstance(report, dict):
        raise HTTPException(
            status_code=502,
            detail="Porchlight report has an unexpected shape.",
        )
    return _guard_porchlight_report_completeness(report)


def _guard_porchlight_report_completeness(report: dict) -> dict:
    checks = report.get("checks")
    if not isinstance(checks, list):
        raise HTTPException(
            status_code=502,
            detail="Porchlight report has an unexpected checks shape.",
        )

    observed = {
        str(check.get("name"))
        for check in checks
        if isinstance(check, dict) and check.get("name")
    }
    missing = sorted(set(PORCHLIGHT_REQUIRED_CHECKS) - observed)
    if not missing:
        return report

    guarded = dict(report)
    guarded_checks = [
        check
        for check in checks
        if not (
            isinstance(check, dict)
            and check.get("name") == PORCHLIGHT_COMPLETENESS_CHECK
        )
    ]
    guarded_checks.insert(
        0,
        {
            "name": PORCHLIGHT_COMPLETENESS_CHECK,
            "status": "fail",
            "severity": "high",
            "summary": "Porchlight report is incomplete; required checks are missing.",
            "detail": ", ".join(missing),
            "metadata": {
                "expected_checks": list(PORCHLIGHT_REQUIRED_CHECKS),
                "observed_checks": sorted(observed),
                "missing_checks": missing,
                "reported_check_count": len(checks),
            },
        },
    )
    guarded["checks"] = guarded_checks
    guarded["counts"] = _porchlight_counts(guarded_checks)
    guarded["status"] = _porchlight_status(guarded["counts"])
    guarded["severity"] = _porchlight_severity(guarded_checks)
    return guarded


def _porchlight_counts(checks: list[object]) -> dict[str, int]:
    counts = {"checks": 0, "passing": 0, "warning": 0, "failing": 0}
    for check in checks:
        if not isinstance(check, dict):
            continue
        counts["checks"] += 1
        status = check.get("status")
        if status == "pass":
            counts["passing"] += 1
        elif status == "warn":
            counts["warning"] += 1
        else:
            counts["failing"] += 1
    return counts


def _porchlight_status(counts: dict[str, int]) -> str:
    if counts["failing"]:
        return "fail"
    if counts["warning"]:
        return "warn"
    return "pass"


def _porchlight_severity(checks: list[object]) -> str:
    severity = "info"
    for check in checks:
        if not isinstance(check, dict):
            continue
        candidate = str(check.get("severity") or "info")
        if _SEVERITY_RANK.get(candidate, 0) > _SEVERITY_RANK[severity]:
            severity = candidate
    return severity


def _load_rotation_config() -> dict:
    path = _REPO_ROOT / "scripts" / "secrets_rotation.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"secrets": {}}
    if not isinstance(data, dict):
        return {"secrets": {}}
    return data


def _keyturner_secret_class(name: str, spec: dict, verify_type: str) -> str:
    secret_class = "db_password" if spec.get("requires_alter_role") else "secret"
    if name.endswith("_API_KEY"):
        secret_class = "api_key"
    elif verify_type == "jwt_exp" or name.startswith("ALPHA_SERVICE_TOKEN"):
        secret_class = "service_jwt"
    elif name.endswith("_TOKEN"):
        secret_class = "service_token"
    if "GMAIL_REFRESH_TOKEN" in name:
        secret_class = "oauth_refresh_token"
    elif "GMAIL_CLIENT_SECRET" in name:
        secret_class = "oauth_client_secret"
    elif name.startswith("CLOUDFLARE_API"):
        secret_class = "cloudflare_api_token"
    elif name.startswith("CLOUDFLARE_TUNNEL"):
        secret_class = "cloudflare_tunnel_token"
    elif name.startswith("MATTERMOST_WEBHOOK"):
        secret_class = "webhook_url"
    elif name.startswith("MATTERMOST_"):
        secret_class = "mattermost_token"
    elif name.startswith("PUSHOVER_"):
        secret_class = "pushover_token"
    elif name in {"ALPHA_PIN", "JARVIS_FAMILY_SMOKE_PIN"}:
        secret_class = "admin_pin"
    return secret_class


def _keyturner_dry_run_status(secret: dict) -> str:
    if secret["status"] in {"failed", "untracked"}:
        return "blocked"
    rotation_path = str(secret.get("rotation_path") or "")
    if secret.get("requires_approval"):
        return "approval_required"
    if secret.get("requires_console_rotation") or "_console" in rotation_path:
        return "console_required"
    if "manual" in rotation_path or "runbook" in rotation_path:
        return "manual_runbook"
    return "ready"


def build_keyturner_summaries(secrets: list[dict]) -> dict[str, object]:
    oauth_items = [
        {
            "secret_name": item["secret_name"],
            "status": item["status"],
            "verify_status": item.get("verify_status"),
            "days_until_due": item.get("days_until_due"),
        }
        for item in secrets
        if str(item.get("secret_class") or "").startswith("oauth_")
    ]
    oauth_attention = [
        item
        for item in oauth_items
        if item["status"] in {"due_soon", "due", "failed", "untracked"}
        or item.get("verify_status") == "failed"
    ]

    dry_run_items = []
    for item in secrets:
        dry_status = _keyturner_dry_run_status(item)
        dry_run_items.append(
            {
                "secret_name": item["secret_name"],
                "status": dry_status,
                "rotation_path": item.get("rotation_path"),
                "reason": (
                    "Requires approval"
                    if dry_status == "approval_required"
                    else "Requires provider console"
                    if dry_status == "console_required"
                    else "Manual runbook"
                    if dry_status == "manual_runbook"
                    else "Secret health blocks dry-run"
                    if dry_status == "blocked"
                    else "Ready for scripted dry-run"
                ),
            }
        )

    due_items = [
        {
            "secret_name": item["secret_name"],
            "status": item["status"],
            "days_until_due": item.get("days_until_due"),
            "next_due_at": item.get("next_due_at"),
        }
        for item in secrets
        if item.get("days_until_due") is not None
    ]
    due_items.sort(key=lambda item: int(item["days_until_due"]))
    return {
        "oauth_health": {
            "managed": len(oauth_items),
            "healthy": len(oauth_items) - len(oauth_attention),
            "attention": len(oauth_attention),
            "items": oauth_items,
        },
        "rotation_dry_run": {
            "runnable": sum(1 for item in dry_run_items if item["status"] == "ready"),
            "approval_gated": sum(
                1 for item in dry_run_items if item["status"] == "approval_required"
            ),
            "console_required": sum(
                1 for item in dry_run_items if item["status"] == "console_required"
            ),
            "manual_runbook": sum(
                1 for item in dry_run_items if item["status"] == "manual_runbook"
            ),
            "blocked": sum(1 for item in dry_run_items if item["status"] == "blocked"),
            "items": dry_run_items,
        },
        "forecast": {
            "due": sum(1 for item in due_items if int(item["days_until_due"]) <= 0),
            "next_7_days": sum(
                1 for item in due_items if 0 < int(item["days_until_due"]) <= 7
            ),
            "next_30_days": sum(
                1 for item in due_items if 0 < int(item["days_until_due"]) <= 30
            ),
            "items": due_items[:12],
        },
    }


async def _safe_payload(label: str, coro):
    try:
        return await coro
    except Exception as exc:  # pragma: no cover - defensive endpoint aggregation
        logger.warning("warden posture source failed label=%s error=%s", label, exc)
        return None


def _warden_hardening_state(
    warden: dict | None,
    crew: list[dict],
) -> dict[str, str]:
    warden_metadata = warden.get("metadata") if isinstance(warden, dict) else {}
    if not isinstance(warden_metadata, dict):
        warden_metadata = {}
    sweep = next((agent for agent in crew if agent.get("agent_id") == "sweep"), None)
    sweep_metadata = sweep.get("metadata") if isinstance(sweep, dict) else {}
    if not isinstance(sweep_metadata, dict):
        sweep_metadata = {}

    active = (
        warden_metadata.get("active_network_hardening")
        or sweep_metadata.get("active_hardening")
        or "service_tls_cert_renewal"
    )
    next_item = (
        warden_metadata.get("next_network_hardening")
        or sweep_metadata.get("active_hardening")
        or active
    )
    return {"active_hardening": str(active), "next_hardening": str(next_item)}


async def _probe_port(
    url: str,
    node: str,
    port: int,
    service: str,
    expected: bool,
) -> dict:
    code = await asyncio.to_thread(_curl_http_code, url, "GET", "3", None)
    reachable = code > 0 and code < 600
    return {
        "node": node,
        "port": port,
        "service": service,
        "reachable": reachable,
        "expected": expected,
    }


@security_router.get("/jwt-check")
async def jwt_check():
    base = BRAIN_URL.rstrip("/")
    protected_routes = [
        {"route": "GET /v1/mesh/status", "path": "/v1/mesh/status", "method": "GET"},
        {"route": "GET /v1/home/summary", "path": "/v1/home/summary", "method": "GET"},
        {
            "route": "GET /v1/costs/summary",
            "path": "/v1/costs/summary",
            "method": "GET",
        },
        {"route": "POST /v1/ask", "path": "/v1/ask", "method": "POST"},
        {"route": "GET /v1/buddy/events", "path": "/v1/buddy/events", "method": "GET"},
        {
            "route": "GET /v1/tasks/graphs",
            "path": "/v1/tasks/graphs",
            "method": "GET",
        },
        {
            "route": "POST /v1/logs/diagnose",
            "path": "/v1/logs/diagnose",
            "method": "POST",
        },
        {
            "route": "GET /v1/security/rls-status",
            "path": "/v1/security/rls-status",
            "method": "GET",
        },
    ]
    skip_routes = [
        {
            "route": "GET /health",
            "path": "/health",
            "method": "GET",
            "expected": 200,
            "body": None,
        },
        {
            "route": "POST /v1/auth/pin",
            "path": "/v1/auth/pin",
            "method": "POST",
            "expected": 422,
            "body": json.dumps({}),
        },
    ]

    async def run_protected(spec: dict) -> dict:
        url = f"{base}{spec['path']}"
        code = await asyncio.to_thread(
            _curl_http_code,
            url,
            spec["method"],
            "5",
            "{}" if spec["method"] == "POST" else None,
        )
        ok = code in (401, 403)
        return {
            "route": spec["route"],
            "expected": 401,
            "actual": code,
            "pass": ok,
            "type": "protected",
        }

    async def run_skip(spec: dict) -> dict:
        url = f"{base}{spec['path']}"
        expected = int(spec["expected"])
        code = await asyncio.to_thread(
            _curl_http_code,
            url,
            spec["method"],
            "5",
            spec.get("body"),
        )
        ok = code == expected
        return {
            "route": spec["route"],
            "expected": expected,
            "actual": code,
            "pass": ok,
            "type": "skip",
        }

    tasks = [run_protected(s) for s in protected_routes] + [
        run_skip(s) for s in skip_routes
    ]
    checks = await asyncio.gather(*tasks)
    passing = sum(1 for c in checks if c["pass"])
    failing = len(checks) - passing
    return {
        "total": len(checks),
        "passing": passing,
        "failing": failing,
        "checks": list(checks),
    }


@security_router.get("/rls-status")
async def rls_status():
    raw = await asyncio.to_thread(_run_psql_rls_sync)
    tables_out: list[dict] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        parts = line.split("|", 4)
        if len(parts) < 5:
            continue
        table = parts[0].strip()
        if not table:
            continue
        rls_enabled_bool = parts[1].strip() == "true"
        force_enabled_bool = parts[2].strip() == "true"
        policy_count = int(parts[3].strip() or "0")
        policy_str = parts[4].strip() or "none"
        rls = "enabled" if rls_enabled_bool else "disabled"
        force_rls = "enabled" if force_enabled_bool else "disabled"
        tables_out.append(
            {
                "table": table,
                "rls": rls,
                "force_rls": force_rls,
                "policy": policy_str,
                "policy_count": policy_count,
                "protected": rls_enabled_bool and force_enabled_bool,
            }
        )

    rls_enabled = 0
    rls_disabled = 0
    force_rls_enabled = 0
    force_rls_disabled = 0
    protected_tables = 0
    for row in tables_out:
        rls = row["rls"]
        if rls == "enabled":
            rls_enabled += 1
        else:
            rls_disabled += 1
        if row["force_rls"] == "enabled":
            force_rls_enabled += 1
        else:
            force_rls_disabled += 1
        if row["protected"]:
            protected_tables += 1

    return {
        "total_tables": len(tables_out),
        "rls_enabled": rls_enabled,
        "rls_disabled": rls_disabled,
        "force_rls_enabled": force_rls_enabled,
        "force_rls_disabled": force_rls_disabled,
        "protected_tables": protected_tables,
        "tables": tables_out,
    }


@security_router.get("/child-profiles")
async def child_profiles(request: Request):
    from brain.db.pool import get_pool
    from brain.db.rls import platform_admin_connection
    from brain.middleware.scopes import check_scopes

    check_scopes(request, "security.read", "security_read")
    pool = get_pool()
    async with platform_admin_connection(
        source="http", audit_actor="security_child_profiles", pool=pool
    ) as conn:
        profile_rows = await conn.fetch(
            """
            SELECT id, display_name, role, child_age, max_rating
            FROM public.alpha_profiles
            WHERE active = true AND role = 'child'
            ORDER BY id
            """
        )
        rls_rows = await conn.fetch(
            """
            SELECT c.relname,
                   c.relrowsecurity AS rls_enabled,
                   c.relforcerowsecurity AS force_enabled,
                   COALESCE(p.policy_count, 0) AS policy_count
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            LEFT JOIN (
                SELECT polrelid, COUNT(*) AS policy_count
                FROM pg_policy
                GROUP BY polrelid
            ) p ON p.polrelid = c.oid
            WHERE n.nspname = 'public'
              AND c.relname = ANY($1::text[])
            """,
            list(_CHILD_SENSITIVE_TABLES),
        )
        legacy_rows = await conn.fetch(
            """
            SELECT tablename, policyname
            FROM pg_policies
            WHERE schemaname = 'public'
              AND policyname = ANY($1::text[])
            ORDER BY tablename, policyname
            """,
            list(_LEGACY_CHILD_POLICIES),
        )

    table_status = {
        row["relname"]: {
            "rls": bool(row["rls_enabled"]),
            "force_rls": bool(row["force_enabled"]),
            "policy_count": int(row["policy_count"]),
        }
        for row in rls_rows
    }
    missing_tables = [
        table for table in _CHILD_SENSITIVE_TABLES if table not in table_status
    ]
    weak_tables = [
        table
        for table, status in table_status.items()
        if not status["rls"] or not status["force_rls"] or status["policy_count"] < 1
    ]
    legacy_policies = [f"{row['tablename']}.{row['policyname']}" for row in legacy_rows]
    db_layer_ok = not missing_tables and not weak_tables
    policy_hygiene_ok = not legacy_policies

    profiles = []
    for row in profile_rows:
        scopes = _profile_scopes(row["role"])
        scopes_ok = scopes == ["ask", "chat.read", "health.read"]
        surfaces = ["voice", "avatar"]
        profiles.append(
            {
                "id": row["id"],
                "name": row["display_name"],
                "age": row["child_age"],
                "max_rating": row["max_rating"],
                "scopes": scopes,
                "allowed_surfaces": surfaces,
                "app_layer": scopes_ok,
                "db_layer": db_layer_ok,
                "content_filter": row["max_rating"] in {"all_ages", "age_8_plus"},
                "surface_filter": "dashboard" not in surfaces,
                "notes": (
                    "Child profile is limited to Avatar/voice surfaces and non-vault scopes."
                    if scopes_ok
                    else "Child profile has broader scopes than expected."
                ),
            }
        )

    overall = "full"
    recommendations: list[str] = []
    if not profiles:
        overall = "attention"
        recommendations.append("No active child profiles were found.")
    if not db_layer_ok:
        overall = "attention"
        recommendations.append("Review child-sensitive table RLS/FORCE RLS coverage.")
    if not policy_hygiene_ok:
        overall = "attention"
        recommendations.append(
            "Drop legacy child policies after confirming replacements."
        )
    if any(not p["app_layer"] or not p["content_filter"] for p in profiles):
        overall = "attention"
        recommendations.append("Tighten child scopes or rating ceilings.")

    return {
        "profiles": profiles,
        "overall": overall,
        "recommendation": " ".join(recommendations)
        if recommendations
        else "Avatar child-safety controls are enforced by profile scopes plus database RLS/FORCE RLS.",
        "sensitive_tables": table_status,
        "missing_tables": missing_tables,
        "weak_tables": weak_tables,
        "legacy_child_policies": legacy_policies,
    }


@security_router.get("/perimeter")
async def perimeter():
    base_brain = BRAIN_URL.rstrip("/")
    gw = GATEWAY_URL.rstrip("/")
    ep = ENDPOINT_URL.rstrip("/")
    sb = SANDBOX_URL.rstrip("/")

    port_specs: list[tuple[str, str, int, str, bool]] = [
        ("brain", f"{base_brain}/health", 8186, "FastAPI", True),
        (
            "brain",
            "https://localhost:5432/health",
            5432,
            "Postgres",
            False,
        ),
        (
            "brain",
            "http://localhost:3100/ready",
            3100,
            "Loki",
            True,
        ),
        (
            "brain",
            "http://localhost:11434/api/tags",
            11434,
            "Ollama",
            True,
        ),
        ("gateway", f"{gw}/health", 8283, "FastAPI", True),
        ("endpoint", f"{ep}/health", 4100, "nginx", True),
        ("sandbox", f"{sb}/health", 5001, "forge", True),
    ]

    port_tasks = [
        _probe_port(url, node, port, service, exp)
        for node, url, port, service, exp in port_specs
    ]
    ts_future = asyncio.to_thread(_tailscale_status_sync)

    ports_result, ts_result = await asyncio.gather(
        asyncio.gather(*port_tasks),
        ts_future,
    )
    ts_active, ts_nodes = ts_result

    return {
        "cors": {
            "allowed_origins": [
                "https://jarvis-endpoint.tail40ed36.ts.net:4100",
            ],
            "locked": True,
        },
        "ports": list(ports_result),
        "tailscale": {
            "active": ts_active,
            "node_count": ts_nodes,
        },
    }


@security_router.get("/porchlight")
async def porchlight_report(request: Request):
    """Return the latest Porchlight security sweep report."""
    from brain.middleware.scopes import check_scopes

    check_scopes(request, "security.read", "security_read")
    report = await asyncio.to_thread(_load_porchlight_report)
    return {
        "report_path": str(_PORCHLIGHT_REPORT_PATH),
        "report": report,
    }


@security_router.get("/keyturner-status")
async def keyturner_status(request: Request):
    """Return Keyturner's managed rotation inventory without secret values."""
    from brain.db.pool import get_pool
    from brain.db.rls import platform_admin_connection
    from brain.middleware.scopes import check_scopes

    check_scopes(request, "security.read", "security_read")
    config = _load_rotation_config()
    configured = (
        config.get("secrets") if isinstance(config.get("secrets"), dict) else {}
    )
    pool = get_pool()
    async with platform_admin_connection(
        source="http", audit_actor="security_keyturner_status", pool=pool
    ) as conn:
        rows = await conn.fetch(
            """
            SELECT secret_name, last_rotated_at, rotation_days, next_due_at,
                   days_until_due, last_verify_status
            FROM public.v_secret_rotation_status
            """
        )

    ledger = {row["secret_name"]: row for row in rows}
    secrets = []
    for name in sorted(configured.keys()):
        spec = configured[name] if isinstance(configured[name], dict) else {}
        row = ledger.get(name)
        verify_type = (
            spec.get("verify", {}).get("type")
            if isinstance(spec.get("verify"), dict)
            else ""
        )
        secret_class = _keyturner_secret_class(name, spec, verify_type)

        if row is None:
            status = "untracked"
            days_until_due = None
            last_rotated_at = None
            next_due_at = None
            verify_status = None
        else:
            days_until_due = row["days_until_due"]
            verify_status = row["last_verify_status"]
            if verify_status == "failed":
                status = "failed"
            elif days_until_due is not None and days_until_due <= 0:
                status = "due"
            elif days_until_due is not None and days_until_due <= 14:
                status = "due_soon"
            else:
                status = "healthy"
            last_rotated_at = row["last_rotated_at"].isoformat()
            next_due_at = row["next_due_at"].isoformat()

        secrets.append(
            {
                "secret_name": name,
                "description": spec.get("description", name),
                "secret_class": secret_class,
                "rotation_days": int(spec.get("rotation_days") or 0),
                "requires_approval": bool(spec.get("requires_alter_role")),
                "requires_console_rotation": bool(
                    spec.get("requires_console_rotation")
                ),
                "rotation_path": spec.get("rotation_path"),
                "status": status,
                "last_rotated_at": last_rotated_at,
                "next_due_at": next_due_at,
                "days_until_due": days_until_due,
                "verify_status": verify_status,
            }
        )

    counts = {
        "managed": len(secrets),
        "healthy": sum(1 for item in secrets if item["status"] == "healthy"),
        "attention": sum(
            1
            for item in secrets
            if item["status"] in {"untracked", "failed", "due", "due_soon"}
        ),
        "approval_gated": sum(1 for item in secrets if item["requires_approval"]),
    }
    return {
        "agent_id": "keyturner",
        "display_name": "Keyturner",
        "mode": "approval_gated",
        "counts": counts,
        **build_keyturner_summaries(secrets),
        "secrets": secrets,
    }


@security_router.get("/warden-status")
async def warden_status(request: Request):
    """Return Warden's security-agent crew without exposing secrets."""
    from brain.db.pool import get_pool
    from brain.db.rls import platform_admin_connection
    from brain.middleware.scopes import check_scopes
    from brain.routes.mesh import get_cert_status
    from brain.services import unifi_client

    check_scopes(request, "security.read", "security_read")
    managed_ids = list(SECURITY_MANAGED_AGENT_IDS)
    pool = get_pool()
    async with platform_admin_connection(
        source="http", audit_actor="security_warden_status", pool=pool
    ) as conn:
        rows = await conn.fetch(
            """
            SELECT a.agent_id, a.display_name, a.purpose, a.risk_tier, a.status,
                   a.enabled, a.cadence, a.allowed_skills, a.allowed_scopes,
                   a.metadata,
                   lr.status AS last_run_status,
                   lr.last_run_at AS last_run_at,
                   le.severity AS last_event_severity,
                   le.title AS last_event_title,
                   le.created_at AS last_event_at
            FROM public.alpha_agents a
            LEFT JOIN LATERAL (
                SELECT status, COALESCE(completed_at, started_at, created_at) AS last_run_at
                FROM public.alpha_agent_runs
                WHERE agent_id = a.agent_id
                ORDER BY COALESCE(completed_at, started_at, created_at) DESC,
                         created_at DESC
                LIMIT 1
            ) lr ON TRUE
            LEFT JOIN LATERAL (
                SELECT severity, title, created_at
                FROM public.alpha_agent_events
                WHERE agent_id = a.agent_id
                ORDER BY created_at DESC
                LIMIT 1
            ) le ON TRUE
            WHERE a.agent_id = ANY($1::text[])
            ORDER BY array_position($1::text[], a.agent_id)
            """,
            managed_ids,
        )
        honeypot_hits_24h = int(
            await conn.fetchval(
                """
                SELECT COUNT(*)
                FROM public.alpha_honeypot_events
                WHERE captured_at >= NOW() - INTERVAL '24 hours'
                """
            )
            or 0
        )
        sweep_report_rows = await conn.fetch(
            """
            SELECT DISTINCT ON (payload->>'node')
                   payload->>'node' AS node,
                   severity,
                   title,
                   message,
                   payload,
                   notification_status,
                   created_at
            FROM public.alpha_agent_events
            WHERE agent_id = 'sweep'
              AND event_type = 'sweep.tls_report'
              AND payload ? 'node'
            ORDER BY payload->>'node', created_at DESC
            """
        )

    agents = []
    for row in rows:
        metadata = (
            json.loads(row["metadata"])
            if isinstance(row["metadata"], str)
            else dict(row["metadata"] or {})
        )
        event_severity = row["last_event_severity"]
        needs_attention = (
            not bool(row["enabled"])
            or row["status"] != "active"
            or event_severity in {"critical", "error", "warning", "needs_input"}
        )
        agents.append(
            {
                "agent_id": row["agent_id"],
                "display_name": row["display_name"],
                "purpose": row["purpose"],
                "risk_tier": row["risk_tier"],
                "status": row["status"],
                "enabled": row["enabled"],
                "cadence": row["cadence"],
                "allowed_skills": list(row["allowed_skills"] or []),
                "allowed_scopes": list(row["allowed_scopes"] or []),
                "metadata": metadata,
                "last_run_status": row["last_run_status"],
                "last_run_at": row["last_run_at"].isoformat()
                if row["last_run_at"]
                else None,
                "last_event_severity": event_severity,
                "last_event_title": row["last_event_title"],
                "last_event_at": row["last_event_at"].isoformat()
                if row["last_event_at"]
                else None,
                "needs_attention": needs_attention,
            }
        )

    warden = next((agent for agent in agents if agent["agent_id"] == "warden"), None)
    crew = [agent for agent in agents if agent["agent_id"] != "warden"]
    crew_attention = sum(1 for agent in crew if agent["needs_attention"])
    (
        jwt,
        rls,
        child,
        perim,
        certs,
        keyturner,
        porchlight,
        unifi_health,
    ) = await asyncio.gather(
        _safe_payload("jwt", jwt_check()),
        _safe_payload("rls", rls_status()),
        _safe_payload("child", child_profiles(request)),
        _safe_payload("perimeter", perimeter()),
        _safe_payload("certs", get_cert_status()),
        _safe_payload("keyturner", keyturner_status(request)),
        _safe_payload("porchlight", porchlight_report(request)),
        _safe_payload("unifi", unifi_client.get_health_check()),
    )
    posture_score = build_warden_posture_score(
        jwt=jwt,
        rls=rls,
        child=child,
        perimeter=perim,
        certs=certs,
        keyturner=keyturner,
        porchlight=porchlight,
        unifi_health=unifi_health,
        crew=crew,
        honeypot_hits_24h=honeypot_hits_24h,
    )
    trade_guard_financial_evidence = build_trade_guard_financial_evidence(porchlight)
    routed_controls = owner_routes(
        [
            control
            for control in posture_score.get("controls", [])
            if control.get("status") != "pass"
        ]
    )
    ticket_candidates = auto_ticket_candidates(routed_controls)
    checked_at = datetime.now(UTC)
    weekly_brief = weekly_security_brief(
        status="pass" if not routed_controls else "warning",
        managed_count=len(crew),
        healthy_count=len(crew) - crew_attention,
        routes=routed_controls,
        checked_at=checked_at,
    )
    hardening_state = _warden_hardening_state(warden, crew)
    sweep_tls_reports = _sweep_report_summary(sweep_report_rows, now=checked_at)
    return {
        "supervisor": warden,
        "agents": crew,
        "counts": {
            "managed": len(crew),
            "enabled": sum(1 for agent in crew if agent["enabled"]),
            "active": sum(1 for agent in crew if agent["status"] == "active"),
            "attention": crew_attention,
        },
        **hardening_state,
        "posture_score": posture_score,
        "trade_guard_financial_evidence": trade_guard_financial_evidence,
        "sweep_tls_reports": sweep_tls_reports,
        "owner_routes": routed_controls,
        "weekly_brief": weekly_brief,
        "auto_ticket_candidates": ticket_candidates,
    }


@security_router.post(
    "/sentinel-report", response_model=SentinelReportResponse, status_code=202
)
async def sentinel_report(
    request: Request, report: SentinelReportIn
) -> SentinelReportResponse:
    """Accept a Forge Sentinel scan summary and surface it as a Warden event."""
    from brain.middleware.scopes import check_scopes

    check_scopes(request, "security.write", "security_write")
    result = await emit_agent_event(
        AgentEvent(
            agent_id="warden",
            event_type="warden.sentinel_report",
            title=f"Sentinel scan: {report.repo_slug}",
            message=_sentinel_event_message(report),
            severity=_sentinel_event_severity(report.severity_counts),
            channel_key="security_alerts",
            payload={
                "source": "forge_sentinel",
                "repo_slug": report.repo_slug,
                "commit_sha": report.commit_sha,
                "branch": report.branch,
                "scan_id": report.scan_id,
                "scanner": report.scanner,
                "findings_total": report.findings_total,
                "severity_counts": report.severity_counts,
                "finding_ids": report.finding_ids[:100],
                "top_findings": [
                    item.model_dump() for item in report.top_findings[:10]
                ],
            },
            correlation_id=f"sentinel:{report.repo_slug}:{report.commit_sha}:{report.scan_id}",
        ),
        pool=get_pool(),
    )
    return SentinelReportResponse(
        accepted=True,
        event_id=result.event_id,
        notification_status=result.notification_status,
    )


@security_router.post(
    "/sweep-report", response_model=SweepReportResponse, status_code=202
)
async def sweep_report(request: Request) -> SweepReportResponse:
    """Accept a signed node-local Sweep TLS report."""
    raw_body = await request.body()
    header_node = _verify_sweep_report_signature(request, raw_body)
    try:
        report = SweepReportIn.model_validate_json(raw_body)
    except ValidationError as exc:
        raise HTTPException(
            status_code=400, detail="invalid_sweep_report_body"
        ) from exc
    if header_node != report.node:
        raise HTTPException(status_code=400, detail="sweep_report_node_mismatch")

    severity = _sweep_report_severity(report)
    result = await emit_agent_event(
        AgentEvent(
            agent_id="sweep",
            event_type="sweep.tls_report",
            title=f"Sweep TLS report: {report.node}",
            message=_sweep_report_message(report),
            severity=severity,
            channel_key="security_alerts",
            notify=severity in {"warning", "error", "critical"},
            payload=_sweep_report_event_payload(report),
            correlation_id=f"sweep:tls:{report.node}:{report.reported_at or report.cert_expires_at or 'unknown'}",
        ),
        pool=get_pool(),
    )
    return SweepReportResponse(
        accepted=True,
        event_id=result.event_id,
        notification_status=result.notification_status,
        severity=severity,
    )


@security_router.get("/agent-events", response_model=SecurityAgentEventsResponse)
async def security_agent_events(
    request: Request,
    limit: int = Query(default=25, ge=1, le=100),
    severity: Literal[
        "debug", "info", "needs_input", "warning", "error", "critical", "all"
    ] = Query(default="all"),
) -> SecurityAgentEventsResponse:
    """Return managed security-agent events for the Security dashboard."""
    from brain.db.pool import get_pool
    from brain.db.rls import platform_admin_connection
    from brain.middleware.scopes import check_scopes

    check_scopes(request, "security.read", "security_read")
    managed_ids = list(SECURITY_MANAGED_AGENT_IDS)
    filters = ["agent_id = ANY($1::text[])"]
    params: list = [managed_ids]
    if severity != "all":
        params.append(severity)
        filters.append(f"severity = ${len(params)}")
    params.append(limit)
    where = " AND ".join(filters)
    pool = get_pool()
    async with platform_admin_connection(
        source="http", audit_actor="security_agent_events", pool=pool
    ) as conn:
        rows = await conn.fetch(
            f"""
            SELECT id, agent_id, run_id, event_type, severity, title, message,
                   correlation_id, channel_key, notification_status,
                   notification_error, payload, notification_result, created_at,
                   notified_at
            FROM public.alpha_agent_events
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT ${len(params)}
            """,
            *params,
        )
    return SecurityAgentEventsResponse(
        count=len(rows),
        events=[_security_agent_event_from_row(row) for row in rows],
    )


@security_router.get("/secrets-audit")
async def secrets_audit(limit: int = Query(default=50, ge=1, le=500)):
    """Return recent secret access events from Postgres."""
    try:
        from brain.db.pool import get_pool
        from brain.db.rls import platform_admin_connection

        pool = get_pool()
        async with platform_admin_connection(
            source="http", audit_actor="security_secrets_audit", pool=pool
        ) as conn:
            rows = await conn.fetch(
                """
                SELECT key_name, source, accessed_at, node
                FROM secret_access_log
                ORDER BY accessed_at DESC
                LIMIT $1
                """,
                limit,
            )
        events = [
            {
                "key": r["key_name"],
                "source": r["source"],
                "accessed_at": r["accessed_at"].isoformat(),
                "node": r["node"],
            }
            for r in rows
        ]
        unique_keys = len({e["key"] for e in events})
        return {
            "total_events": len(events),
            "unique_keys": unique_keys,
            "events": events,
        }
    except Exception as e:
        logger.warning("secrets-audit query failed: %s", e)
        return {"total_events": 0, "unique_keys": 0, "events": [], "error": str(e)}
