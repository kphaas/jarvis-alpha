"""
Alpha Brain UniFi proxy — calls alpha Gateway only (never UDM Pro directly).
"""

import asyncio
import json
import os
import subprocess
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["unifi"])


def _gateway_url() -> str:
    return os.environ.get(
        "ALPHA_GATEWAY_URL", "https://jarvis-gateway.tail40ed36.ts.net:8282"
    ).rstrip("/")


def _gateway_get(path: str) -> dict[str, Any]:
    base = _gateway_url()
    token = os.environ.get("GATEWAY_TOKEN", "")
    url = f"{base}{path}"
    try:
        proc = subprocess.run(
            ["curl", "-sk", "-H", f"x-jarvis-token: {token}", url],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if proc.returncode != 0:
            err = (proc.stderr or "").strip() or f"curl exit {proc.returncode}"
            return {"ok": False, "error": err}
        raw = (proc.stdout or "").strip()
        if not raw:
            return {"ok": False, "error": "empty response"}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "data": data}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def _proxy(path: str) -> Any:
    result = await asyncio.to_thread(_gateway_get, path)
    if not result.get("ok"):
        raise HTTPException(
            status_code=502, detail=result.get("error", "gateway error")
        )
    return result["data"]


@router.get("/v1/unifi/status")
async def unifi_status():
    return await _proxy("/v1/unifi/status")


@router.get("/v1/unifi/wan")
async def unifi_wan():
    return await _proxy("/v1/unifi/wan")


@router.get("/v1/unifi/clients")
async def unifi_clients():
    return await _proxy("/v1/unifi/clients")


@router.get("/v1/unifi/summary")
async def unifi_summary():
    return await _proxy("/v1/unifi/summary")
