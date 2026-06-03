from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import uuid
from datetime import date, datetime, timezone
from typing import Any, Literal, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from brain.core.db import get_db
from brain.db.pool import get_pool
from brain.middleware.jwt_auth import require_auth
from brain.services.gateway_egress import GatewayEgressError, call_gateway_proxy_sync

router = APIRouter(prefix="/v1/costs", tags=["costs"])

_COMBINED_POWER_RE = re.compile(
    r"Combined Power \(CPU \+ GPU \+ ANE\):\s*([\d.]+)\s*mW", re.IGNORECASE
)

NODE_WATTS: dict[str, float] = {
    "Gateway": 10.0,
    "Endpoint": 10.0,
    "Sandbox": 15.0,
}


def _month_bounds_utc() -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return start, now


def _rfc3339_z(dt: datetime) -> str:
    s = dt.astimezone(timezone.utc).isoformat()
    if s.endswith("+00:00"):
        return s[:-6] + "Z"
    return s


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
                "-sSk",
                "--max-time",
                "15",
                "-w",
                "\n%{http_code}",
                "https://jarvis-forge.tail40ed36.ts.net:5001/api/costs/report",
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


# --- ANTHROPIC ADMIN API ---


def _sum_cost_report_usd(payload: dict[str, Any]) -> float:
    total = 0.0
    for bucket in payload.get("data") or []:
        for r in bucket.get("results") or []:
            amt = r.get("amount")
            if amt is None:
                continue
            v = float(amt)
            # Admin API amounts are in minor units; example: 123.45 -> $1.23
            total += v / 100.0
    return total


def _walk_key_costs(obj: Any, out: dict[str, float]) -> None:
    if isinstance(obj, dict):
        kn = obj.get("key_name")
        if isinstance(kn, str) and kn:
            cost = obj.get("cost_usd")
            if cost is not None:
                out[kn] = out.get(kn, 0.0) + float(cost)
            amt = obj.get("amount")
            if amt is not None and kn:
                out[kn] = out.get(kn, 0.0) + float(amt) / 100.0
        for v in obj.values():
            _walk_key_costs(v, out)
    elif isinstance(obj, list):
        for x in obj:
            _walk_key_costs(x, out)


def _usage_bucket_calls(payload: dict[str, Any]) -> int:
    n = 0
    for bucket in payload.get("data") or []:
        n += len(bucket.get("results") or [])
    return n


async def _anthropic_key_split_from_db() -> tuple[float, float, int, float]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT key_name, COALESCE(SUM(cost_usd), 0) AS s, COUNT(*) AS c
            FROM alpha_cloud_costs
            WHERE provider = 'anthropic'
              AND created_at >= date_trunc('month', now())
            GROUP BY key_name
            """
        )
    core = 0.0
    forge = 0.0
    total = 0.0
    calls = 0
    for r in rows:
        s = float(r["s"])
        c = int(r["c"])
        calls += c
        total += s
        kn = (r["key_name"] or "").lower()
        if "forge" in kn:
            forge += s
        elif "core" in kn or kn == "jarvis_core":
            core += s
    return core, forge, calls, total


def _get_anthropic_mtd_sync() -> dict[str, Any]:
    start, end = _month_bounds_utc()
    start_s = _rfc3339_z(start)
    end_s = _rfc3339_z(end)
    try:
        usage_payload = call_gateway_proxy_sync(
            "anthropic_admin",
            {
                "path": "/v1/organizations/usage_report/messages",
                "params": {
                    "starting_at": start_s,
                    "ending_at": end_s,
                    "bucket_width": "1d",
                },
            },
            timeout_s=65,
        ).get("payload")
        cost_payload = call_gateway_proxy_sync(
            "anthropic_admin",
            {
                "path": "/v1/organizations/cost_report",
                "params": {
                    "starting_at": start_s,
                    "ending_at": end_s,
                    "bucket_width": "1d",
                },
            },
            timeout_s=65,
        ).get("payload")
        if not isinstance(usage_payload, dict) or not isinstance(cost_payload, dict):
            raise RuntimeError("Gateway returned invalid Anthropic admin payload")

        total_usd = _sum_cost_report_usd(cost_payload)
        by_key: dict[str, float] = {}
        _walk_key_costs(usage_payload, by_key)
        _walk_key_costs(cost_payload, by_key)
        calls_mtd = _usage_bucket_calls(usage_payload)

        jarvis_core_usd = 0.0
        jarvis_forge_usd = 0.0
        for k, v in by_key.items():
            kl = k.lower()
            if "forge" in kl:
                jarvis_forge_usd += v
            elif "core" in kl or kl == "jarvis_core":
                jarvis_core_usd += v

        return {
            "total_usd": total_usd,
            "jarvis_core_usd": jarvis_core_usd,
            "jarvis_forge_usd": jarvis_forge_usd,
            "calls_mtd": calls_mtd,
            "by_key": by_key,
        }
    except Exception as e:
        return {
            "total_usd": 0.0,
            "jarvis_core_usd": 0.0,
            "jarvis_forge_usd": 0.0,
            "calls_mtd": 0,
            "by_key": {},
            "error": str(e),
        }


def _extract_gcp_billing_total(data: dict[str, Any]) -> float:
    total = 0.0
    for k in ("costsTotal", "totalCost", "total_cost", "amount"):
        if k in data and data[k] is not None:
            try:
                return float(data[k])
            except (TypeError, ValueError):
                pass
    for row in data.get("rows") or data.get("tableRows") or []:
        if isinstance(row, dict):
            for kk, vv in row.items():
                if "cost" in kk.lower() and isinstance(vv, (int, float)):
                    total += float(vv)
    return total


async def _get_anthropic_mtd() -> dict[str, Any]:
    base = await asyncio.to_thread(_get_anthropic_mtd_sync)
    enrich = base.get("error") or float(base.get("total_usd") or 0) <= 0
    if enrich:
        core, forge, calls, db_total = await _anthropic_key_split_from_db()
        if db_total > 0 or core or forge or calls:
            base["total_usd"] = max(float(base.get("total_usd") or 0), db_total)
            base["jarvis_core_usd"] = max(float(base.get("jarvis_core_usd") or 0), core)
            base["jarvis_forge_usd"] = max(
                float(base.get("jarvis_forge_usd") or 0), forge
            )
            base["calls_mtd"] = max(int(base.get("calls_mtd") or 0), calls)
    base.setdefault("jarvis_core_usd", 0.0)
    base.setdefault("jarvis_forge_usd", 0.0)
    base.setdefault("calls_mtd", 0)
    base.setdefault("total_usd", 0.0)
    base.setdefault("by_key", {})
    return base


# --- GCP BILLING / GEMINI ---


async def _gemini_mtd_from_db() -> tuple[float, Optional[str]]:
    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COALESCE(SUM(cost_usd), 0) AS t FROM alpha_cloud_costs "
                "WHERE provider = 'gemini' AND created_at >= date_trunc('month', now())"
            )
        return float(row["t"]) if row else 0.0, None
    except Exception as e:
        return 0.0, str(e)


def _get_gemini_mtd_sync() -> dict[str, Any]:
    try:
        response = call_gateway_proxy_sync(
            "google_billing",
            {"currency_code": "USD"},
            timeout_s=60,
        )
        data = response.get("payload")
        if not isinstance(data, dict):
            return {"_skip": True}
        total = _extract_gcp_billing_total(data)
        if total <= 0:
            return {"_skip": True}
        return {
            "total_usd": total,
            "source": "gcp_api",
        }
    except GatewayEgressError as e:
        return {"_skip": True, "_gateway_error": str(e)}
    except Exception:
        return {"_skip": True}


async def _get_gemini_mtd() -> dict[str, Any]:
    err_note: Optional[str] = None
    try:
        r = await asyncio.to_thread(_get_gemini_mtd_sync)
        if (
            isinstance(r, dict)
            and r.get("total_usd") is not None
            and not r.get("_skip")
        ):
            return {"total_usd": float(r["total_usd"]), "source": "gcp_api"}
        if r.get("_import_error"):
            err_note = "google-auth not available"
    except Exception as e:
        err_note = str(e)

    total, db_err = await _gemini_mtd_from_db()
    out: dict[str, Any] = {"total_usd": total, "source": "internal"}
    errs = [x for x in (err_note, db_err) if x]
    if errs:
        out["error"] = "; ".join(errs)
    return out


# --- BUDGET ---


class BudgetLimitIn(BaseModel):
    monthly_limit_usd: float


@router.get("/budget")
async def get_budget(_: str = Depends(require_auth)):
    pool = get_pool()
    async with pool.acquire() as conn:
        configs = await conn.fetch(
            "SELECT provider, monthly_limit_usd FROM alpha_budget_config ORDER BY provider"
        )
    out: list[dict[str, Any]] = []
    async with pool.acquire() as conn:
        for row in configs:
            prov = row["provider"]
            limit = float(row["monthly_limit_usd"])
            mtd = await conn.fetchval(
                """
                SELECT COALESCE(SUM(cost_usd), 0)
                FROM alpha_cloud_costs
                WHERE provider = $1 AND created_at >= date_trunc('month', now())
                """,
                prov,
            )
            mtd_f = float(mtd or 0)
            remaining = limit - mtd_f
            pct = (mtd_f / limit * 100.0) if limit > 0 else 0.0
            out.append(
                {
                    "provider": prov,
                    "monthly_limit_usd": limit,
                    "mtd_usd": mtd_f,
                    "remaining_usd": remaining,
                    "pct_used": round(pct, 2),
                }
            )
    return out


@router.post("/budget/{provider}")
async def set_budget_limit(
    provider: str,
    body: BudgetLimitIn,
    _: str = Depends(require_auth),
    conn: asyncpg.Connection = Depends(get_db),
):
    row = await conn.fetchrow(
        """
        UPDATE alpha_budget_config
        SET monthly_limit_usd = $1, updated_at = now()
        WHERE provider = $2
        RETURNING provider, monthly_limit_usd, updated_at
        """,
        body.monthly_limit_usd,
        provider,
    )
    if not row:
        raise HTTPException(status_code=404, detail="unknown provider")
    return {
        "provider": row["provider"],
        "monthly_limit_usd": float(row["monthly_limit_usd"]),
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


# --- PER-OUTCOME COSTS ---


@router.get("/outcomes")
async def get_outcomes(
    _: str = Depends(require_auth),
    conn: asyncpg.Connection = Depends(get_db),
):
    rows = await conn.fetch(
        """
        SELECT session_type,
               COUNT(*) AS run_count,
               COALESCE(SUM(cost_usd), 0) AS total_usd,
               COALESCE(AVG(cost_usd), 0) AS avg_usd
        FROM alpha_cloud_costs
        WHERE created_at >= date_trunc('month', now())
        GROUP BY session_type
        ORDER BY session_type NULLS LAST
        """
    )
    return [
        {
            "session_type": r["session_type"],
            "run_count": int(r["run_count"]),
            "total_usd": float(r["total_usd"]),
            "avg_usd": float(r["avg_usd"]),
        }
        for r in rows
    ]


# --- HARDWARE ---


@router.get("/hardware")
async def get_hardware(
    _: str = Depends(require_auth),
    conn: asyncpg.Connection = Depends(get_db),
):
    rows = await conn.fetch(
        "SELECT node_name, cost_usd, years, monthly_usd "
        "FROM alpha_hardware_config ORDER BY node_name"
    )
    items = [
        {
            "node_name": r["node_name"],
            "cost_usd": float(r["cost_usd"]),
            "years": int(r["years"]),
            "monthly_usd": float(r["monthly_usd"]),
        }
        for r in rows
    ]
    total_m = sum(x["monthly_usd"] for x in items)
    return {"nodes": items, "total_monthly_usd": total_m}


# --- PERPLEXITY CREDIT ---


class PerplexityCreditIn(BaseModel):
    balance_usd: float
    spent_usd: float = 0.0


@router.get("/perplexity")
async def get_perplexity_credit(
    _: str = Depends(require_auth),
    conn: asyncpg.Connection = Depends(get_db),
):
    row = await conn.fetchrow(
        "SELECT balance_usd, spent_usd, updated_at "
        "FROM alpha_perplexity_credit ORDER BY id DESC LIMIT 1"
    )
    if not row:
        return {"balance_usd": 0.0, "spent_usd": 0.0, "updated_at": None}
    return {
        "balance_usd": float(row["balance_usd"]),
        "spent_usd": float(row["spent_usd"]),
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


@router.post("/perplexity")
async def upsert_perplexity_credit(
    body: PerplexityCreditIn,
    _: str = Depends(require_auth),
    conn: asyncpg.Connection = Depends(get_db),
):
    row = await conn.fetchrow(
        """
        INSERT INTO alpha_perplexity_credit (id, balance_usd, spent_usd, updated_at)
        VALUES (1, $1, $2, now())
        ON CONFLICT (id) DO UPDATE SET
            balance_usd = EXCLUDED.balance_usd,
            spent_usd = EXCLUDED.spent_usd,
            updated_at = now()
        RETURNING balance_usd, spent_usd, updated_at
        """,
        body.balance_usd,
        body.spent_usd,
    )
    return {
        "balance_usd": float(row["balance_usd"]),
        "spent_usd": float(row["spent_usd"]),
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


# --- SUMMARY HELPERS ---


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


async def _summary_credit_row() -> dict[str, float]:
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


async def _summary_hardware_monthly_usd() -> float:
    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COALESCE(SUM(monthly_usd), 0) AS m FROM alpha_hardware_config"
            )
        return float(row["m"]) if row else 0.0
    except Exception:
        return 0.0


async def _summary_budget_for_summary() -> list[dict[str, Any]]:
    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            configs = await conn.fetch(
                "SELECT provider, monthly_limit_usd FROM alpha_budget_config ORDER BY provider"
            )
        out: list[dict[str, Any]] = []
        async with pool.acquire() as conn:
            for row in configs:
                prov = row["provider"]
                limit = float(row["monthly_limit_usd"])
                mtd = await conn.fetchval(
                    """
                    SELECT COALESCE(SUM(cost_usd), 0)
                    FROM alpha_cloud_costs
                    WHERE provider = $1 AND created_at >= date_trunc('month', now())
                    """,
                    prov,
                )
                mtd_f = float(mtd or 0)
                pct = (mtd_f / limit * 100.0) if limit > 0 else 0.0
                out.append(
                    {
                        "provider": prov,
                        "monthly_limit_usd": limit,
                        "mtd_usd": mtd_f,
                        "pct_used": round(pct, 2),
                    }
                )
        return out
    except Exception:
        return []


async def _summary_outcomes_for_summary() -> list[dict[str, Any]]:
    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT session_type,
                       COUNT(*) AS run_count,
                       COALESCE(AVG(cost_usd), 0) AS avg_usd
                FROM alpha_cloud_costs
                WHERE created_at >= date_trunc('month', now())
                GROUP BY session_type
                ORDER BY session_type NULLS LAST
                """
            )
        return [
            {
                "session_type": r["session_type"],
                "run_count": int(r["run_count"]),
                "avg_usd": float(r["avg_usd"]),
            }
            for r in rows
        ]
    except Exception:
        return []


async def _summary_perplexity_row() -> dict[str, float]:
    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT balance_usd, spent_usd FROM alpha_perplexity_credit ORDER BY id DESC LIMIT 1"
            )
        if not row:
            return {"balance_usd": 0.0, "spent_usd": 0.0}
        return {
            "balance_usd": float(row["balance_usd"]),
            "spent_usd": float(row["spent_usd"]),
        }
    except Exception:
        return {"balance_usd": 0.0, "spent_usd": 0.0}


async def _summary_perplexity_mtd_usd() -> float:
    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COALESCE(SUM(cost_usd), 0) AS t FROM alpha_cloud_costs "
                "WHERE provider = 'perplexity' AND created_at >= date_trunc('month', now())"
            )
        return float(row["t"]) if row else 0.0
    except Exception:
        return 0.0


async def _summary_avg_cloud_cost() -> float:
    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT COALESCE(AVG(cost_usd), 0) AS a
                FROM alpha_cloud_costs
                WHERE created_at >= date_trunc('month', now())
                """
            )
        return float(row["a"]) if row else 0.0
    except Exception:
        return 0.0


@router.get("/summary")
async def get_summary(_: str = Depends(require_auth)):
    (
        subscriptions_monthly_usd,
        credit,
        power_monthly_usd,
        forge_raw,
        anthropic_mtd,
        gemini_mtd,
        hardware_monthly_usd,
        budget_rows,
        outcomes_rows,
        perplexity_credit,
        perplexity_mtd_usd,
        avg_cloud,
    ) = await asyncio.gather(
        _summary_subscriptions_monthly_usd(),
        _summary_credit_row(),
        _summary_power_monthly_usd(),
        _get_forge_costs(),
        _get_anthropic_mtd(),
        _get_gemini_mtd(),
        _summary_hardware_monthly_usd(),
        _summary_budget_for_summary(),
        _summary_outcomes_for_summary(),
        _summary_perplexity_row(),
        _summary_perplexity_mtd_usd(),
        _summary_avg_cloud_cost(),
    )

    forge_monthly_usd = float(forge_raw.get("total_usd") or 0)

    anthropic_total = float(anthropic_mtd.get("total_usd") or 0)
    gemini_total = float(gemini_mtd.get("total_usd") or 0)
    api_spend_mtd = anthropic_total + gemini_total + perplexity_mtd_usd

    true_monthly_tco = (
        subscriptions_monthly_usd
        + power_monthly_usd
        + hardware_monthly_usd
        + api_spend_mtd
    )

    try:
        local_pct = float(os.environ.get("LOCAL_ROUTING_PCT", "0") or 0)
    except ValueError:
        local_pct = 0.0
    savings_vs_cloud_usd = max(0.0, local_pct * avg_cloud)

    return {
        "subscriptions_monthly_usd": subscriptions_monthly_usd,
        "credit": credit,
        "perplexity": perplexity_credit,
        "power_monthly_usd": power_monthly_usd,
        "hardware_monthly_usd": hardware_monthly_usd,
        "true_monthly_tco": true_monthly_tco,
        "forge_monthly_usd": forge_monthly_usd,
        "api": {
            "anthropic": {
                "total_usd": anthropic_total,
                "jarvis_core_usd": float(anthropic_mtd.get("jarvis_core_usd") or 0),
                "jarvis_forge_usd": float(anthropic_mtd.get("jarvis_forge_usd") or 0),
            },
            "gemini": {
                "total_usd": gemini_total,
                "source": gemini_mtd.get("source", "internal"),
            },
            "perplexity_mtd_usd": perplexity_mtd_usd,
        },
        "budget": budget_rows,
        "outcomes": outcomes_rows,
        "savings_vs_cloud_usd": savings_vs_cloud_usd,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
