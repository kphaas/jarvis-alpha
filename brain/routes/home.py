import asyncio
import time
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from brain.db.pool import get_pool

logger = logging.getLogger(__name__)
router = APIRouter()

CACHE_TTL = 60
_cache: dict = {}
_cache_time: float = 0.0

NODE_URLS = {
    "gateway": "https://100.112.63.25:8282/health",
    "endpoint": "https://100.87.223.31:4000/health",
}

CERT_PATH = "/Users/jarvisbrain/jarvis/certs/brain.crt"


async def _ping_node(name: str, url: str) -> dict:
    import subprocess
    import asyncio

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
    try:
        import subprocess

        result = await asyncio.to_thread(
            lambda: subprocess.run(
                ["openssl", "x509", "-in", CERT_PATH, "-noout", "-enddate"],
                capture_output=True,
                text=True,
            )
        )
        line = result.stdout.strip()
        date_str = line.replace("notAfter=", "")
        from datetime import datetime

        exp = datetime.strptime(date_str, "%b %d %H:%M:%S %Y %Z").replace(
            tzinfo=timezone.utc
        )
        now = datetime.now(timezone.utc)
        return (exp - now).days
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
        return None


async def _last_overnight() -> dict | None:
    pool = get_pool()
    try:
        row = await pool.fetchrow(
            "SELECT status, created_at FROM overnight_runs ORDER BY created_at DESC LIMIT 1"
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
