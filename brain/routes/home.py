import asyncio
import os
import time
from datetime import datetime, timezone
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from brain.db.pool import get_pool
from brain.config.logging_config import get_logger
from brain.config.node_addresses import (
    GATEWAY_URL,
    ENDPOINT_URL,
    SANDBOX_URL,
)

logger = get_logger("alpha_brain")
router = APIRouter()

CACHE_TTL = 60
_cache: dict = {}
_cache_time: float = 0.0

CERT_PATH = os.getenv("ALPHA_CERT_PATH", "")

NODE_URLS = {
    "gateway": f"{GATEWAY_URL}/health",
    "endpoint": f"{ENDPOINT_URL}/health",
    "sandbox": f"{SANDBOX_URL}/health",
}


async def _ping_node(name: str, url: str) -> dict:
    import subprocess

    start = time.monotonic()
    try:
        result = await asyncio.to_thread(
            lambda: subprocess.run(
                [
                    "curl",
                    "-sk",
                    "--max-time",
                    "3",
                    "-o",
                    "/dev/null",
                    "-w",
                    "%{http_code}",
                    url,
                ],
                capture_output=True,
                text=True,
            )
        )
        latency_ms = round((time.monotonic() - start) * 1000)
        reachable = result.stdout.strip() == "200"
        return {"reachable": reachable, "latency_ms": latency_ms if reachable else None}
    except Exception as e:
        logger.warning(f"Ping {name} failed: {e}")
        return {"reachable": False, "latency_ms": None}


async def _cert_days_remaining() -> int | None:
    if not CERT_PATH:
        logger.warning("ALPHA_CERT_PATH not set — skipping cert check")
        return None
    try:
        import subprocess

        result = await asyncio.to_thread(
            lambda: subprocess.run(
                ["openssl", "x509", "-in", CERT_PATH, "-noout", "-enddate"],
                capture_output=True,
                text=True,
            )
        )
        date_str = result.stdout.strip().replace("notAfter=", "")
        exp = datetime.strptime(date_str, "%b %d %H:%M:%S %Y %Z").replace(
            tzinfo=timezone.utc
        )
        return (exp - datetime.now(timezone.utc)).days
    except Exception as e:
        logger.warning(f"Cert check failed: {e}")
        return None


async def _costs_today() -> float | None:
    pool = get_pool()
    try:
        row = await pool.fetchrow(
            "SELECT COALESCE(SUM(cost_usd), 0) AS total FROM alpha_cloud_costs "
            "WHERE created_at >= date_trunc('day', now())"
        )
        return float(row["total"]) if row else 0.0
    except Exception as e:
        logger.warning(f"Cost query failed: {e}")
        return 0.0


async def _last_overnight() -> dict | None:
    pool = get_pool()
    try:
        row = await pool.fetchrow(
            "SELECT status, created_at FROM alpha_task_graphs "
            "ORDER BY created_at DESC LIMIT 1"
        )
        if not row:
            return None
        return {"status": row["status"], "ran_at": row["created_at"].isoformat()}
    except Exception as e:
        logger.warning(f"Overnight query failed: {e}")
        return None


@router.get("/v1/home/summary")
async def home_summary(request: Request):
    global _cache, _cache_time

    if _cache and (time.monotonic() - _cache_time) < CACHE_TTL:
        return JSONResponse(_cache)

    node_pings, cert_days, costs, overnight = await asyncio.gather(
        asyncio.gather(*[_ping_node(n, u) for n, u in NODE_URLS.items()]),
        _cert_days_remaining(),
        _costs_today(),
        _last_overnight(),
    )

    nodes = {"brain": {"reachable": True, "latency_ms": 0}}
    for name, result in zip(NODE_URLS.keys(), node_pings):
        nodes[name] = result

    _cache = {
        "nodes": nodes,
        "costs_today_usd": costs,
        "cert_days_remaining": cert_days,
        "last_overnight_run": overnight,
        "cached_at": datetime.now(timezone.utc).isoformat(),
    }
    _cache_time = time.monotonic()

    return JSONResponse(_cache)
