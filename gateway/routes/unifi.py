"""
Alpha Gateway UniFi proxy — talks to UDM Pro (local/self-signed TLS).
"""

import asyncio
import json
import os
import subprocess
import tempfile
from typing import Any

from fastapi import APIRouter

from jarvis_common.logging_config import get_logger
from jarvis_common.secrets import get_secret

logger = get_logger("alpha_gateway")

router = APIRouter(tags=["unifi"])

_session_lock = asyncio.Lock()
_logged_in = False
_cookie_jar_path: str | None = None


def _base_url() -> str:
    try:
        url = get_secret("UNIFI_BASE_URL")
    except KeyError as exc:
        raise RuntimeError(
            "UNIFI_BASE_URL is not set in environment — check ~/jarvis/.secrets on Gateway"
        ) from exc
    return url.rstrip("/")


def _cookie_jar() -> str:
    global _cookie_jar_path
    if _cookie_jar_path is None:
        fd, path = tempfile.mkstemp(prefix="jarvis-unifi-", suffix=".cookies")
        os.close(fd)
        _cookie_jar_path = path
    return _cookie_jar_path


def _curl(
    args: list[str], *, timeout_sec: float = 15.0
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["curl", "-sk", *args],
        capture_output=True,
        text=True,
        timeout=timeout_sec,
        check=False,
    )


def _login_sync() -> None:
    try:
        user = get_secret("UNIFI_USER")
        password = get_secret("UNIFI_PASS")
    except KeyError as exc:
        raise RuntimeError("UniFi credentials are not configured on Gateway") from exc
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
        raise RuntimeError(
            f"UniFi login failed: http_code={code!r} stderr={proc.stderr!r}"
        )


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


def _fetch_json_sync(path: str) -> dict[str, Any]:
    base = _base_url()
    jar = _cookie_jar()
    proc = _curl(["-b", jar, "-c", jar, f"{base}{path}"])
    if proc.returncode != 0:
        detail = (proc.stderr or "").strip() or f"curl exit {proc.returncode}"
        raise RuntimeError(detail)
    try:
        return json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError("UniFi returned non-json response") from exc


async def _fetch_json(path: str) -> dict[str, Any]:
    await ensure_unifi_session()
    return await asyncio.to_thread(_fetch_json_sync, path)


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
        data = await _fetch_json("/proxy/network/api/s/default/stat/health")
        subsystems = data.get("data", [])
        wan = next((s for s in subsystems if s.get("subsystem") == "wan"), {})
        www = next((s for s in subsystems if s.get("subsystem") == "www"), {})
        gw_stats = wan.get("gw_system-stats", {})
        xput_up = www.get("xput_up", 0.0)
        xput_down = www.get("xput_down", 0.0)
        speedtest_ok = www.get("speedtest_status", "") not in ("", "Error")
        return {
            "wan_status": "up" if wan.get("status") == "ok" else "unknown",
            "wan_up_mbps": round(xput_up, 1) if speedtest_ok and xput_up else None,
            "wan_down_mbps": round(xput_down, 1)
            if speedtest_ok and xput_down
            else None,
            "latency_ms": www.get("latency"),
            "uptime_sec": www.get("uptime"),
            "speedtest_status": www.get("speedtest_status", "unknown"),
            "isp_name": wan.get("isp_name"),
            "gw_name": wan.get("gw_name"),
            "gw_cpu_pct": gw_stats.get("cpu"),
            "gw_mem_pct": gw_stats.get("mem"),
        }
    except Exception as e:
        logger.exception("unifi_wan")
        return _error_payload(e)


@router.get("/v1/unifi/clients")
async def unifi_clients() -> dict[str, Any]:
    try:
        data = await _fetch_json("/proxy/network/api/s/default/stat/sta")
        clients = data.get("data", [])
        sanitized = [_client_summary(client) for client in clients]
        return {
            "client_count": len(clients),
            "wired_count": sum(1 for c in clients if c.get("is_wired")),
            "wireless_count": sum(1 for c in clients if not c.get("is_wired")),
            "clients": sanitized,
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


@router.get("/v1/unifi/health-check")
async def unifi_health_check() -> dict[str, Any]:
    try:
        status = await unifi_status()
        wan = await unifi_wan()
        clients = await unifi_clients()
        devices_payload = await _fetch_json("/proxy/network/api/s/default/stat/device")
        devices = devices_payload.get("data", [])
        device_summaries = [_device_summary(device) for device in devices]
        offline_count = sum(1 for device in device_summaries if not device["online"])
        errors: list[str] = []

        if not status.get("reachable"):
            errors.append("controller_unreachable")
        if wan.get("error"):
            errors.append("wan_read_failed")
        elif wan.get("wan_status") not in {"up", "ok"}:
            errors.append(f"wan_status:{wan.get('wan_status', 'unknown')}")
        if clients.get("error"):
            errors.append("clients_read_failed")
        if offline_count:
            errors.append(f"offline_devices:{offline_count}")

        health_status = "ok"
        if errors:
            health_status = "critical" if not status.get("reachable") else "degraded"

        return {
            "reachable": bool(status.get("reachable", False)),
            "status": health_status,
            "wan_status": wan.get("wan_status", "unknown"),
            "client_count": clients.get("client_count"),
            "wired_count": clients.get("wired_count"),
            "wireless_count": clients.get("wireless_count"),
            "ap_count": sum(1 for device in device_summaries if device["kind"] == "ap"),
            "switch_count": sum(
                1 for device in device_summaries if device["kind"] == "switch"
            ),
            "gateway_count": sum(
                1 for device in device_summaries if device["kind"] == "gateway"
            ),
            "offline_device_count": offline_count,
            "gw_cpu_pct": wan.get("gw_cpu_pct"),
            "gw_mem_pct": wan.get("gw_mem_pct"),
            "errors": errors,
            "devices": device_summaries,
        }
    except Exception as e:
        logger.exception("unifi_health_check")
        return _error_payload(e)


def _client_summary(client: dict[str, Any]) -> dict[str, Any]:
    return {
        "mac": client.get("mac"),
        "ip": client.get("ip"),
        "hostname": client.get("hostname"),
        "name": client.get("name") or client.get("hostname"),
        "is_wired": bool(client.get("is_wired")),
        "network": client.get("network") or client.get("network_name"),
        "essid": client.get("essid"),
        "last_seen": client.get("last_seen"),
        "vendor": client.get("oui"),
    }


def _device_summary(device: dict[str, Any]) -> dict[str, Any]:
    kind = _device_kind(device)
    return {
        "mac": device.get("mac"),
        "ip": device.get("ip"),
        "name": device.get("name") or device.get("displayable_version"),
        "model": device.get("model"),
        "kind": kind,
        "online": device.get("state") == 1,
        "version": device.get("version"),
        "uptime_sec": device.get("uptime"),
    }


def _device_kind(device: dict[str, Any]) -> str:
    device_type = str(device.get("type") or "").lower()
    model = str(device.get("model") or "").lower()
    if device_type in {"uap", "ap"} or model.startswith("uap"):
        return "ap"
    if device_type in {"usw", "switch"} or model.startswith("usw"):
        return "switch"
    if device_type in {"ugw", "udm", "gateway"} or model.startswith(("udm", "ucg")):
        return "gateway"
    return device_type or "other"
