"""Security dashboard API — JWT check, RLS status, child profiles, perimeter."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from urllib.parse import urlparse

from fastapi import APIRouter, Query

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
SELECT t.tablename,
       CASE WHEN t.rowsecurity THEN 'enabled' ELSE 'disabled' END as rls_status,
       COALESCE(p.policyname, 'none') as policy_name
FROM pg_tables t
LEFT JOIN pg_policies p ON t.tablename = p.tablename
WHERE t.schemaname = 'public'
ORDER BY t.tablename;
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
    agg: dict[str, dict] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        parts = line.split("|", 2)
        if len(parts) < 3:
            continue
        table, rls_s, pol = parts[0].strip(), parts[1].strip(), parts[2].strip()
        if not table:
            continue
        if table not in agg:
            agg[table] = {"rls": "disabled", "policy_names": set()}
        if rls_s == "enabled":
            agg[table]["rls"] = "enabled"
        if pol and pol != "none":
            agg[table]["policy_names"].add(pol)

    tables_out: list[dict] = []
    rls_enabled = 0
    rls_disabled = 0
    for name in sorted(agg.keys()):
        row = agg[name]
        rls = row["rls"]
        names = row["policy_names"]
        policy_str = ",".join(sorted(names)) if names else "none"
        if rls == "enabled":
            rls_enabled += 1
        else:
            rls_disabled += 1
        tables_out.append({"table": name, "rls": rls, "policy": policy_str})

    return {
        "total_tables": len(tables_out),
        "rls_enabled": rls_enabled,
        "rls_disabled": rls_disabled,
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
                "db_layer": False,
                "content_filter": True,
                "notes": "App-layer content filtering active. DB-layer RLS pending Alpha-2.",
            },
            {
                "name": "Sloane",
                "age": 5,
                "app_layer": True,
                "db_layer": False,
                "content_filter": True,
                "notes": "App-layer content filtering active. DB-layer RLS pending Alpha-2.",
            },
        ],
        "overall": "partial",
        "recommendation": "Child profile RLS at database layer is the top security priority.",
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


@security_router.get("/secrets-audit")
async def secrets_audit(limit: int = Query(default=50, ge=1, le=500)):
    """Return recent secret access events from Postgres."""
    try:
        from brain.db.pool import get_pool

        pool = get_pool()
        async with pool.acquire() as conn:
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
