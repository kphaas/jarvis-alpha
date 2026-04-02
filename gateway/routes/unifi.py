"""
Alpha Gateway UniFi proxy — talks to UDM Pro (local TLS, curl -sk).
"""
import asyncio
import json
import logging
import os
import subprocess
import tempfile
from typing import Any

from fastapi import APIRouter

logger = logging.getLogger("jarvis.gateway.unifi")

router = APIRouter(tags=["unifi"])

_session_lock = asyncio.Lock()
_logged_in = False
_cookie_jar_path: str | None = None


def _base_url() -> str:
    url = os.environ.get("UNIFI_BASE_URL", "")
    if not url:
        raise RuntimeError("UNIFI_BASE_URL is not set in environment — check ~/jarvis/.secrets on Gateway")
    return url.rstrip("/")


def _cookie_jar() -> str:
    global _cookie_jar_path
    if _cookie_jar_path is None:
        fd, path = tempfile.mkstemp(prefix="jarvis-unifi-", suffix=".cookies")
        os.close(fd)
        _cookie_jar_path = path
    return _cookie_jar_path


def _curl(args: list[str], *, timeout_sec: float = 15.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["curl", "-sk", *args],
        capture_output=True,
        text=True,
        timeout=timeout_sec,
        check=False,
    )


def _login_sync() -> None:
    user = os.environ.get("UNIFI_USER", "")
    password = os.environ.get("UNIFI_PASS", "")
    base = _base_url()
    jar = _cookie_jar()
    body = json.dumps({"username": user, "password": password})
    proc = _curl(
        [
            "-c",
            jar,
            "-b",
            jar,
            "-X",
            "POST",
            "-H",
            "Content-Type: application/json",
            "-d",
            body,
            "-o",
            "/dev/null",
            "-w",
            "%{http_code}",
            f"{base}/api/auth/login",
        ]
    )
    code = (proc.stdout or "").strip()
    if proc.returncode != 0 or not code.startswith("2"):
        raise RuntimeError(f"UniFi login failed: http_code={code!r} stderr={proc.stderr!r}")


async def ensure_unifi_session() -> None:
    """Login once; reuse cookie jar for subsequent authenticated curl calls."""
    global _logged_in
    async with _session_lock:
        if _logged_in:
            return
        await asyncio.to_thread(_login_sync)
        _logged_in = True


def _ping_base_url_sync() -> bool:
    base = _base_url()
    proc = _curl(
        [
            "-o",
            "/dev/null",
            "-w",
            "%{http_code}",
            "--max-time",
            "5",
            f"{base}/",
        ],
        timeout_sec=8.0,
    )
    code = (proc.stdout or "").strip()
    if proc.returncode != 0:
        return False
    if not code or code == "000":
        return False
    try:
        return int(code) < 600
    except ValueError:
        return False


def _error_payload(exc: BaseException) -> dict[str, Any]:
    return {"reachable": False, "error": str(exc)}


@router.get("/v1/unifi/status")
async def unifi_status() -> dict[str, Any]:
    try:
        reachable = await asyncio.to_thread(_ping_base_url_sync)
        return {"reachable": reachable, "auth_mode": "local"}
    except Exception as e:
        logger.exception("unifi_status")
        return _error_payload(e)


@router.get("/v1/unifi/wan")
async def unifi_wan() -> dict[str, Any]:
    try:
        await ensure_unifi_session()
        base = _base_url()
        jar = _cookie_jar()

        def _fetch() -> subprocess.CompletedProcess[str]:
            return _curl(["-b", jar, "-c", jar,
                          f"{base}/proxy/network/api/s/default/stat/health"])

        proc = await asyncio.to_thread(_fetch)
        data = json.loads(proc.stdout or "{}")
        wan = next(
            (s for s in data.get("data", []) if s.get("subsystem") == "wan"), {}
        )
        speedtest = wan.get("speedtest_status", {})
        return {
            "wan_status": "up" if wan.get("status") == "ok" else "unknown",
            "wan_up_mbps": round(speedtest.get("xput_upload", 0), 1) or None,
            "wan_down_mbps": round(speedtest.get("xput_download", 0), 1) or None,
            "latency_ms": wan.get("latency", None),
            "uptime_sec": wan.get("uptime", None),
        }
    except Exception as e:
        logger.exception("unifi_wan")
        return _error_payload(e)


@router.get("/v1/unifi/clients")
async def unifi_clients() -> dict[str, Any]:
    try:
        await ensure_unifi_session()
        base = _base_url()
        jar = _cookie_jar()

        def _fetch() -> subprocess.CompletedProcess[str]:
            return _curl(["-b", jar, "-c", jar,
                          f"{base}/proxy/network/api/s/default/stat/sta"])

        proc = await asyncio.to_thread(_fetch)
        data = json.loads(proc.stdout or "{}")
        clients = data.get("data", [])
        return {
            "client_count": len(clients),
            "wired_count": sum(1 for c in clients if c.get("is_wired")),
            "wireless_count": sum(1 for c in clients if not c.get("is_wired")),
        }
    except Exception as e:
        logger.exception("unifi_clients")
        return _error_payload(e)


@router.get("/v1/unifi/summary")
async def unifi_summary() -> dict[str, Any]:
    try:
        status = await unifi_status()
        wan = await unifi_wan()
        clients = await unifi_clients()
        return {
            "reachable": status.get("reachable", False),
            "wan_up_mbps": wan.get("wan_up_mbps"),
            "wan_down_mbps": wan.get("wan_down_mbps"),
            "client_count": clients.get("client_count"),
            "wan_status": wan.get("wan_status", "unknown"),
        }
    except Exception as e:
        logger.exception("unifi_summary")
        return _error_payload(e)
