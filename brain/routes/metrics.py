from datetime import date, datetime, timezone
from typing import Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from brain.core.db import get_db
from brain.middleware.jwt_auth import require_auth

router = APIRouter(prefix="/v1/metrics", tags=["metrics"])

STATIC_WATTS: dict[str, float] = {
    "Brain": 10.0,
    "Gateway": 10.0,
    "Endpoint": 10.0,
    "Sandbox": 15.0,
}

NODES_ORDER = ("Brain", "Gateway", "Endpoint", "Sandbox")


class PowerReading(BaseModel):
    node_name: str
    watts: float
    cpu_pct: Optional[float] = None
    source: str = "psutil"


@router.post("/power")
async def post_power(
    reading: PowerReading,
    conn: asyncpg.Connection = Depends(get_db),
):
    try:
        await conn.execute(
            """
            INSERT INTO alpha_power_readings (node_name, watts, cpu_pct, source)
            VALUES ($1, $2, $3, $4)
            """,
            reading.node_name,
            reading.watts,
            reading.cpu_pct,
            reading.source,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {
        "status": "ok",
        "node": reading.node_name,
        "watts": reading.watts,
    }


@router.get("/power/current")
async def get_power_current(
    _: str = Depends(require_auth),
    conn: asyncpg.Connection = Depends(get_db),
):
    nodes_out: list[dict] = []
    total = 0.0
    for node_name in NODES_ORDER:
        row = await conn.fetchrow(
            """
            SELECT AVG(watts) AS avg_watts, COUNT(*)::bigint AS samples
            FROM alpha_power_readings
            WHERE node_name = $1
              AND recorded_at >= now() - interval '24 hours'
            """,
            node_name,
        )
        samples = int(row["samples"]) if row else 0
        has_live = samples > 0
        if has_live and row["avg_watts"] is not None:
            avg_w = float(row["avg_watts"])
            src = "live"
        else:
            avg_w = STATIC_WATTS.get(node_name, 10.0)
            src = "static"
        total += avg_w
        nodes_out.append(
            {
                "node_name": node_name,
                "avg_watts_24h": avg_w,
                "sample_count": samples,
                "has_live_data": has_live,
                "source": src,
            }
        )
    return {
        "nodes": nodes_out,
        "total_avg_watts": total,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/power/history")
async def get_power_history(
    _: str = Depends(require_auth),
    conn: asyncpg.Connection = Depends(get_db),
):
    rows = await conn.fetch(
        """
        SELECT node_name, day_start, avg_watts
        FROM alpha_power_daily
        WHERE day_start >= (CURRENT_DATE - interval '30 days')
        ORDER BY node_name, day_start
        """
    )
    by_node: dict[str, list[dict]] = {n: [] for n in NODES_ORDER}
    for r in rows:
        nn = r["node_name"]
        if nn not in by_node:
            continue
        ds = r["day_start"]
        if isinstance(ds, datetime):
            d: date = ds.date()
        else:
            d = ds
        by_node[nn].append({"day": d.isoformat(), "avg_watts": float(r["avg_watts"])})
    return {
        "nodes": [{"node_name": n, "readings": by_node[n]} for n in NODES_ORDER],
    }


@router.post("/power/rollup")
async def post_power_rollup(conn: asyncpg.Connection = Depends(get_db)):
    async with conn.transaction():
        await conn.execute(
            """
            INSERT INTO alpha_power_hourly (node_name, hour_start, avg_watts, sample_count)
            SELECT node_name,
                   date_trunc('hour', recorded_at) AS hour_start,
                   AVG(watts),
                   COUNT(*)::integer
            FROM alpha_power_readings
            WHERE recorded_at < date_trunc('hour', now())
              AND recorded_at >= now() - interval '25 hours'
            GROUP BY node_name, date_trunc('hour', recorded_at)
            ON CONFLICT (node_name, hour_start) DO UPDATE SET
                avg_watts = EXCLUDED.avg_watts,
                sample_count = EXCLUDED.sample_count
            """
        )
        await conn.execute(
            """
            INSERT INTO alpha_power_daily (node_name, day_start, avg_watts, sample_count)
            SELECT node_name,
                   (date_trunc('day', recorded_at))::date AS day_start,
                   AVG(watts),
                   COUNT(*)::integer
            FROM alpha_power_readings
            WHERE recorded_at < date_trunc('day', now())
              AND recorded_at >= now() - interval '32 days'
            GROUP BY node_name, (date_trunc('day', recorded_at))::date
            ON CONFLICT (node_name, day_start) DO UPDATE SET
                avg_watts = EXCLUDED.avg_watts,
                sample_count = EXCLUDED.sample_count
            """
        )
        del_result = await conn.execute(
            """
            DELETE FROM alpha_power_readings
            WHERE recorded_at < now() - interval '30 days'
            """
        )
    parts = del_result.split()
    purged = int(parts[-1]) if parts else 0
    return {"status": "ok", "purged": purged}
