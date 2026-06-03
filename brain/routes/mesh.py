"""
mesh.py — Mesh topology and node health endpoints for jarvis-alpha.
  GET /v1/mesh/status — node_registry + polymorphic health checks
  GET /v1/mesh/certs  — certificate expiry for all nodes
"""

import asyncio
import os
import re
import subprocess
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter

from brain.db.pool import get_pool

router = APIRouter()

_CRITICAL_NODE_NAMES = frozenset({"brain", "gateway", "endpoint"})
_NON_CRITICAL_NAMES = frozenset({"unraid", "air", "udmpro"})
_MOBILE_NAMES = frozenset({"iphone"})


def _ping_node(ip: str) -> dict:
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", "2", ip],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            match = re.search(r"time[=<](\d+\.?\d*)", result.stdout)
            latency = float(match.group(1)) if match else None
            return {"reachable": True, "latency_ms": latency}
        return {"reachable": False, "latency_ms": None}
    except Exception:
        return {"reachable": False, "latency_ms": None}


def _naive_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return (
        dt.replace(tzinfo=timezone.utc)
        if dt.tzinfo is None
        else dt.astimezone(timezone.utc)
    )


def _cert_fields_for_row(
    issued: datetime | None, expires: datetime | None
) -> tuple[str | None, float | None, int | None]:
    i, e = _naive_utc(issued), _naive_utc(expires)
    if i is None or e is None:
        return None, None, None
    now = datetime.now(timezone.utc)
    lifetime_days = (e - i).days
    remaining_days = (e - now).days
    pct = (
        round((remaining_days / lifetime_days) * 100.0, 1) if lifetime_days > 0 else 0.0
    )
    cert_status = "green" if pct > 25 else "amber" if pct > 5 else "red"
    return cert_status, pct, remaining_days


def _curl_code_and_ms(url: str, max_time: int = 5) -> tuple[int | None, float | None]:
    try:
        result = subprocess.run(
            [
                "curl",
                "-sS",
                "--max-time",
                str(max_time),
                "-o",
                "/dev/null",
                "-w",
                "%{http_code}|%{time_total}",
                url,
            ],
            capture_output=True,
            text=True,
            timeout=max_time + 2,
        )
        if result.returncode != 0 or "|" not in result.stdout:
            return None, None
        code_s, t_s = result.stdout.strip().split("|", 1)
        code = int(code_s) if code_s.isdigit() else None
        t_ms = float(t_s) * 1000.0 if t_s else None
        return code, t_ms
    except (subprocess.TimeoutExpired, ValueError, OSError):
        return None, None


def _check_service_row(row: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    ep = row.get("health_endpoint")
    if not ep:
        return "unreachable", {}
    code, t_ms = _curl_code_and_ms(ep, max_time=5)
    if code in (200, 401):
        extra: dict[str, Any] = {}
        if t_ms is not None:
            extra["response_time_ms"] = round(t_ms, 1)
        return "healthy", extra
    return "unreachable", {}


def _check_storage_row(row: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    ip = row.get("tailscale_ip")
    if not ip:
        return "unreachable", {}
    ping = _ping_node(ip)
    return ("online" if ping["reachable"] else "unreachable"), {}


def _check_mobile_row(row: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    ip = row.get("tailscale_ip")
    if not ip:
        return "offline", {}
    ping = _ping_node(ip)
    return ("online" if ping["reachable"] else "offline"), {}


def _run_polymorphic_check(row: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    try:
        nt = (row.get("node_type") or "").lower()
        if nt == "service":
            return _check_service_row(row)
        if nt == "storage":
            return _check_storage_row(row)
        if nt == "mobile":
            return _check_mobile_row(row)
        return "unreachable", {}
    except Exception:
        nt = (row.get("node_type") or "").lower()
        return ("offline" if nt == "mobile" else "unreachable"), {}


def _compute_mesh_status(nodes: list[dict[str, Any]]) -> str:
    for n in nodes:
        if n["name"] in _CRITICAL_NODE_NAMES and n["status"] == "unreachable":
            return "critical"
    for n in nodes:
        if n["name"] in _MOBILE_NAMES:
            continue
        if n["name"] in _NON_CRITICAL_NAMES and n["status"] in (
            "unreachable",
            "offline",
        ):
            return "degraded"
        if n.get("cert_status") in ("amber", "red"):
            return "degraded"
    return "nominal"


@router.get("/v1/mesh/status")
async def get_mesh_status():
    checked_at = datetime.now(timezone.utc).isoformat()
    pool = get_pool()
    rows = await pool.fetch(
        "SELECT * FROM alpha_node_registry WHERE is_active = true ORDER BY name"
    )
    rows = [dict(r) for r in rows]

    async def _check_one(row: dict[str, Any]) -> tuple[dict, str, dict]:
        status, extra = await asyncio.to_thread(_run_polymorphic_check, row)
        return row, status, extra

    try:
        results = await asyncio.wait_for(
            asyncio.gather(*[_check_one(r) for r in rows]),
            timeout=10.0,
        )
    except asyncio.TimeoutError:
        results = []
        for r in rows:
            nt = (r.get("node_type") or "").lower()
            results.append((r, "offline" if nt == "mobile" else "unreachable", {}))

    nodes_out = []
    for row, status, extra in results:
        cert_status, cert_pct, cert_days = _cert_fields_for_row(
            row.get("cert_issued_at"), row.get("cert_expires_at")
        )
        nodes_out.append(
            {
                "name": row["name"],
                "display_name": row["display_name"],
                "role": row["role"],
                "node_type": row["node_type"],
                "tailscale_ip": row.get("tailscale_ip"),
                "status": status,
                "cert_status": cert_status,
                "cert_pct_remaining": cert_pct,
                "cert_days_remaining": cert_days,
                "extra": extra,
            }
        )

    return {
        "mesh_status": _compute_mesh_status(nodes_out),
        "checked_at": checked_at,
        "nodes": nodes_out,
    }


@router.get("/v1/mesh/certs")
async def get_cert_status():
    """
    Cert expiry data, sourced from alpha_node_registry.
    For Brain (or any node where the cert file is local), reads the actual
    cert from disk for ground truth. Otherwise uses cert_expires_at from the DB.

    Add a node to this endpoint by inserting into alpha_node_registry with
    cert_expires_at populated — no code changes required.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT name, display_name, tailscale_ip, health_endpoint,
                   cert_issued_at, cert_expires_at
            FROM alpha_node_registry
            WHERE node_type = 'service'
              AND is_active = true
              AND cert_expires_at IS NOT NULL
            ORDER BY name
            """
        )

    # Local cert overrides — when running on a node, prefer reading the actual
    # cert file from disk over the DB value (catches mid-cycle renewals).
    LOCAL_CERT_PATHS = {
        "brain": os.path.expanduser("~/jarvis/certs/brain.crt"),
    }

    result = []
    for row in rows:
        node_name = row["name"]
        domain = _extract_domain(row["health_endpoint"]) or row["tailscale_ip"] or ""
        expires_dt: datetime | None = row["cert_expires_at"]
        source = "registry"

        # If we have a local cert file for this node, prefer its on-disk truth
        cert_path = LOCAL_CERT_PATHS.get(node_name)
        if cert_path and os.path.exists(cert_path):
            try:
                out = subprocess.run(
                    ["openssl", "x509", "-enddate", "-noout", "-in", cert_path],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if out.returncode == 0:
                    raw = out.stdout.strip().replace("notAfter=", "")
                    expires_dt = datetime.strptime(raw, "%b %d %H:%M:%S %Y %Z").replace(
                        tzinfo=timezone.utc
                    )
                    source = "disk"
            except Exception:
                pass

        if expires_dt is None:
            continue

        days = (expires_dt - datetime.now(timezone.utc)).days
        result.append(
            {
                "node": row["display_name"],
                "domain": domain,
                "expires": expires_dt.strftime("%Y-%m-%d"),
                "days_remaining": days,
                "status": "critical" if days < 14 else "warning" if days < 30 else "ok",
                "source": source,
            }
        )

    return result


def _extract_domain(health_endpoint: str | None) -> str | None:
    """Extract hostname from a https://host:port/path URL."""
    if not health_endpoint:
        return None
    match = re.match(r"https?://([^:/]+)", health_endpoint)
    return match.group(1) if match else None
