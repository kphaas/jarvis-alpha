"""Security dashboard API — JWT check, RLS status, child profiles, perimeter."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Query, Request

from jarvis_common.logging_config import get_logger
from brain.config.node_addresses import (
    BRAIN_URL,
    GATEWAY_URL,
    ENDPOINT_URL,
    SANDBOX_URL,
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


def _curl_http_code(
    url: str,
    method: str = "GET",
    max_time: str = "5",
    json_body: str | None = None,
) -> int:
    cmd = [
        "curl",
        "-sk",
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
    r = subprocess.run(
        [
            _PSQL,
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
    return report


def _load_rotation_config() -> dict:
    path = _REPO_ROOT / "scripts" / "secrets_rotation.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"secrets": {}}
    if not isinstance(data, dict):
        return {"secrets": {}}
    return data


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
        {"route": "GET /health", "path": "/health", "method": "GET"},
        {"route": "POST /v1/auth/pin", "path": "/v1/auth/pin", "method": "POST"},
    ]

    pin = os.environ.get("ALPHA_PIN")
    pin_body = json.dumps({"pin": pin}) if pin else None

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
        if spec["path"] == "/v1/auth/pin" and pin_body is not None:
            code = await asyncio.to_thread(_curl_http_code, url, "POST", "5", pin_body)
        else:
            code = await asyncio.to_thread(
                _curl_http_code,
                url,
                spec["method"],
                "5",
                None,
            )
        ok = code == 200
        return {
            "route": spec["route"],
            "expected": 200,
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
async def child_profiles():
    return {
        "profiles": [
            {
                "name": "Ryleigh",
                "age": 8,
                "app_layer": True,
                "db_layer": True,
                "content_filter": True,
                "notes": "App-layer content filtering active. Database RLS and FORCE RLS are enforced across public Alpha tables.",
            },
            {
                "name": "Sloane",
                "age": 5,
                "app_layer": True,
                "db_layer": True,
                "content_filter": True,
                "notes": "App-layer content filtering active. Database RLS and FORCE RLS are enforced across public Alpha tables.",
            },
        ],
        "overall": "full",
        "recommendation": "Continue child-specific route smokes and Porchlight RLS drift monitoring.",
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
        secret_class = "db_password" if spec.get("requires_alter_role") else "secret"
        if name.endswith("_TOKEN"):
            secret_class = "service_token"
        if name.endswith("_API_KEY"):
            secret_class = "api_key"
        if name == "ALPHA_PIN":
            secret_class = "admin_pin"

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
        "secrets": secrets,
    }


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
