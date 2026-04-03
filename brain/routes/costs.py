from __future__ import annotations

import asyncio
import json
import re
import subprocess
import uuid
from datetime import date, datetime, timezone
from typing import Literal, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from brain.core.db import get_db
from brain.db.pool import get_pool
from brain.middleware.jwt_auth import require_auth

router = APIRouter(prefix="/v1/costs", tags=["costs"])

_COMBINED_POWER_RE = re.compile(
    r"Combined Power \(CPU \+ GPU \+ ANE\):\s*([\d.]+)\s*mW", re.IGNORECASE
)

NODE_WATTS: dict[str, float] = {
    "Gateway": 10.0,
    "Endpoint": 10.0,
    "Sandbox": 15.0,
}


# --- SECTION 1: SUBSCRIPTIONS ---


class SubscriptionIn(BaseModel):
    name: str
    url: Optional[str] = None
    cost_usd: float
    billing: Literal["monthly", "yearly"]
    next_renewal: date


class SubscriptionOut(BaseModel):
    id: uuid.UUID
    name: str
    url: Optional[str] = None
    cost_usd: float
    billing: str
    next_renewal: date
    days_until_renewal: int


def _days_until(next_renewal: date) -> int:
    today = date.today()
    if isinstance(next_renewal, datetime):
        next_renewal = next_renewal.date()
    return (next_renewal - today).days


def _row_to_subscription_out(row: asyncpg.Record) -> SubscriptionOut:
    nr = row["next_renewal"]
    if isinstance(nr, datetime):
        nr = nr.date()
    return SubscriptionOut(
        id=row["id"],
        name=row["name"],
        url=row["url"],
        cost_usd=float(row["cost_usd"]),
        billing=row["billing"],
        next_renewal=nr,
        days_until_renewal=_days_until(nr),
    )


@router.get("/subscriptions", response_model=list[SubscriptionOut])
async def list_subscriptions(
    _: str = Depends(require_auth),
    conn: asyncpg.Connection = Depends(get_db),
):
    rows = await conn.fetch(
        "SELECT id, name, url, cost_usd, billing, next_renewal "
        "FROM alpha_subscriptions ORDER BY next_renewal ASC"
    )
    return [_row_to_subscription_out(r) for r in rows]


@router.post("/subscriptions", response_model=SubscriptionOut)
async def create_subscription(
    body: SubscriptionIn,
    _: str = Depends(require_auth),
    conn: asyncpg.Connection = Depends(get_db),
):
    row = await conn.fetchrow(
        """
        INSERT INTO alpha_subscriptions (name, url, cost_usd, billing, next_renewal)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id, name, url, cost_usd, billing, next_renewal
        """,
        body.name,
        body.url,
        body.cost_usd,
        body.billing,
        body.next_renewal,
    )
    return _row_to_subscription_out(row)


@router.delete("/subscriptions/{sub_id}")
async def delete_subscription(
    sub_id: uuid.UUID,
    _: str = Depends(require_auth),
    conn: asyncpg.Connection = Depends(get_db),
):
    result = await conn.execute(
        "DELETE FROM alpha_subscriptions WHERE id = $1",
        sub_id,
    )
    # asyncpg returns 'DELETE N'
    n = int(result.split()[-1])
    if n == 0:
        raise HTTPException(status_code=404, detail="subscription not found")
    return {"deleted": str(sub_id)}


# --- SECTION 2: CREDIT BALANCE ---


class CreditIn(BaseModel):
    balance_usd: float
    spent_usd: float = 0.0
    pending_usd: float = 0.0


@router.get("/credit")
async def get_credit(
    _: str = Depends(require_auth),
    conn: asyncpg.Connection = Depends(get_db),
):
    row = await conn.fetchrow(
        "SELECT balance_usd, spent_usd, pending_usd, updated_at "
        "FROM alpha_credit_balance ORDER BY id DESC LIMIT 1"
    )
    if not row:
        return {
            "balance_usd": 0,
            "spent_usd": 0,
            "pending_usd": 0,
            "updated_at": None,
        }
    return {
        "balance_usd": float(row["balance_usd"]),
        "spent_usd": float(row["spent_usd"]),
        "pending_usd": float(row["pending_usd"]),
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


@router.post("/credit")
async def upsert_credit(
    body: CreditIn,
    _: str = Depends(require_auth),
    conn: asyncpg.Connection = Depends(get_db),
):
    row = await conn.fetchrow(
        """
        INSERT INTO alpha_credit_balance (id, balance_usd, spent_usd, pending_usd, updated_at)
        VALUES (1, $1, $2, $3, now())
        ON CONFLICT (id) DO UPDATE SET
            balance_usd = EXCLUDED.balance_usd,
            spent_usd = EXCLUDED.spent_usd,
            pending_usd = EXCLUDED.pending_usd,
            updated_at = now()
        RETURNING balance_usd, spent_usd, pending_usd, updated_at
        """,
        body.balance_usd,
        body.spent_usd,
        body.pending_usd,
    )
    return {
        "balance_usd": float(row["balance_usd"]),
        "spent_usd": float(row["spent_usd"]),
        "pending_usd": float(row["pending_usd"]),
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


# --- SECTION 3: POWER ---


class PowerConfigIn(BaseModel):
    rate_per_kwh: float


def _parse_powermetrics_output(text: str) -> float:
    m = _COMBINED_POWER_RE.search(text)
    if not m:
        return 10.0
    mw = float(m.group(1))
    return mw / 1000.0


def _run_powermetrics_sync() -> float:
    try:
        proc = subprocess.run(
            [
                "sudo",
                "powermetrics",
                "--samplers",
                "cpu_power",
                "-n",
                "1",
                "-i",
                "500",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        return _parse_powermetrics_output(proc.stdout + proc.stderr)
    except Exception:
        return 10.0


async def _get_brain_watts() -> float:
    return await asyncio.to_thread(_run_powermetrics_sync)


def _node_costs(
    brain_watts: float, rate_per_kwh: float
) -> tuple[list[dict], float, float]:
    nodes_spec = [("Brain", brain_watts)] + [
        (name, w) for name, w in NODE_WATTS.items()
    ]
    nodes_out: list[dict] = []
    total_watts = 0.0
    total_cost = 0.0
    for name, watts in nodes_spec:
        kwh_monthly = watts * 730.0 / 1000.0
        cost_monthly = kwh_monthly * rate_per_kwh
        nodes_out.append(
            {
                "name": name,
                "watts": watts,
                "kwh_monthly": kwh_monthly,
                "cost_monthly": cost_monthly,
            }
        )
        total_watts += watts
        total_cost += cost_monthly
    return nodes_out, total_watts, total_cost


@router.get("/power")
async def get_power(
    _: str = Depends(require_auth),
    conn: asyncpg.Connection = Depends(get_db),
):
    brain_watts = await _get_brain_watts()
    row = await conn.fetchrow(
        "SELECT rate_per_kwh FROM alpha_power_config WHERE id = 1 LIMIT 1"
    )
    rate = float(row["rate_per_kwh"]) if row else 0.13
    nodes, total_watts, total_cost_monthly = _node_costs(brain_watts, rate)
    return {
        "rate_per_kwh": rate,
        "nodes": nodes,
        "total_watts": total_watts,
        "total_cost_monthly": total_cost_monthly,
    }


@router.post("/power/rate")
async def set_power_rate(
    body: PowerConfigIn,
    _: str = Depends(require_auth),
    conn: asyncpg.Connection = Depends(get_db),
):
    await conn.execute(
        """
        UPDATE alpha_power_config
        SET rate_per_kwh = $1, updated_at = now()
        WHERE id = 1
        """,
        body.rate_per_kwh,
    )
    return {"rate_per_kwh": float(body.rate_per_kwh)}


# --- SECTION 4: FORGE AGGREGATION ---


def _forge_curl_sync() -> dict:
    try:
        proc = subprocess.run(
            [
                "curl",
                "-sS",
                "--max-time",
                "15",
                "-w",
                "\n%{http_code}",
                "http://100.124.172.14:5001/api/costs/report",
            ],
            capture_output=True,
            text=True,
        )
        raw = proc.stdout.strip()
        if "\n" not in raw:
            return {"total_usd": 0, "by_project": [], "error": "unavailable"}
        body, _, code_s = raw.rpartition("\n")
        if int(code_s) != 200:
            return {"total_usd": 0, "by_project": [], "error": "unavailable"}
        data = json.loads(body)
        if not isinstance(data, dict):
            return {"total_usd": 0, "by_project": [], "error": "unavailable"}
        return data
    except Exception:
        return {"total_usd": 0, "by_project": [], "error": "unavailable"}


async def _get_forge_costs() -> dict:
    return await asyncio.to_thread(_forge_curl_sync)


# --- SECTION 5: SUMMARY ---


async def _summary_subscriptions_monthly_usd() -> float:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT cost_usd, billing FROM alpha_subscriptions")
    total = 0.0
    for r in rows:
        c = float(r["cost_usd"])
        if r["billing"] == "monthly":
            total += c
        else:
            total += c / 12.0
    return total


async def _summary_credit_row() -> dict:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT balance_usd, spent_usd, pending_usd "
            "FROM alpha_credit_balance ORDER BY id DESC LIMIT 1"
        )
    if not row:
        return {"balance_usd": 0.0, "spent_usd": 0.0, "pending_usd": 0.0}
    return {
        "balance_usd": float(row["balance_usd"]),
        "spent_usd": float(row["spent_usd"]),
        "pending_usd": float(row["pending_usd"]),
    }


async def _summary_power_monthly_usd() -> float:
    pool = get_pool()
    brain_watts = await _get_brain_watts()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT rate_per_kwh FROM alpha_power_config WHERE id = 1 LIMIT 1"
        )
    rate = float(row["rate_per_kwh"]) if row else 0.13
    _, _, total_cost = _node_costs(brain_watts, rate)
    return total_cost


async def _summary_api_mtd_usd() -> float:
    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COALESCE(SUM(cost_usd), 0) AS total FROM alpha_cloud_costs "
                "WHERE created_at >= date_trunc('month', now())"
            )
        return float(row["total"]) if row else 0.0
    except Exception:
        return 0.0


@router.get("/summary")
async def get_summary(_: str = Depends(require_auth)):
    (
        subscriptions_monthly_usd,
        credit,
        power_monthly_usd,
        forge_raw,
        api_mtd_usd,
    ) = await asyncio.gather(
        _summary_subscriptions_monthly_usd(),
        _summary_credit_row(),
        _summary_power_monthly_usd(),
        _get_forge_costs(),
        _summary_api_mtd_usd(),
    )
    forge_monthly_usd = float(forge_raw.get("total_usd") or 0)
    total_estimated_monthly_usd = (
        subscriptions_monthly_usd + power_monthly_usd + forge_monthly_usd + api_mtd_usd
    )
    return {
        "subscriptions_monthly_usd": subscriptions_monthly_usd,
        "credit": credit,
        "power_monthly_usd": power_monthly_usd,
        "forge_monthly_usd": forge_monthly_usd,
        "api_mtd_usd": api_mtd_usd,
        "total_estimated_monthly_usd": total_estimated_monthly_usd,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
