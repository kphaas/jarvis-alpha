"""Internal cost event ingestion - Gateway -> Brain.

Gateway fires async POST with token usage after each cloud call.
Brain calculates cost_usd from alpha_model_pricing and writes to alpha_cloud_costs.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

import asyncpg
from fastapi import APIRouter, Request
from pydantic import BaseModel

from brain.db.pool import get_pool
from brain.middleware.scopes import check_scopes
from jarvis_common.logging_config import get_logger

logger = get_logger("alpha_brain")

router = APIRouter(prefix="/v1/internal", tags=["internal"])


class CostEvent(BaseModel):
    provider: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    session_type: Optional[str] = None
    key_name: Optional[str] = None
    intent: Optional[str] = None
    executor: Optional[str] = None
    on_behalf_of: Optional[str] = None
    idempotency_key: Optional[str] = None


async def _lookup_pricing(
    pool: asyncpg.Pool, provider: str, model: str, as_of: date
) -> dict | None:
    """Find the most recent pricing row for provider+model on or before as_of."""
    row = await pool.fetchrow(
        """
        SELECT input_per_1m_usd, output_per_1m_usd,
               context_threshold_tokens,
               input_per_1m_usd_long_context, output_per_1m_usd_long_context
        FROM alpha_model_pricing
        WHERE provider = $1 AND model = $2 AND effective_from <= $3
        ORDER BY effective_from DESC
        LIMIT 1
        """,
        provider,
        model,
        as_of,
    )
    return dict(row) if row else None


def _calculate_cost(
    pricing: dict, prompt_tokens: int, completion_tokens: int
) -> Decimal:
    """Calculate cost_usd from pricing row and token counts."""
    input_rate = Decimal(str(pricing["input_per_1m_usd"]))
    output_rate = Decimal(str(pricing["output_per_1m_usd"]))
    million = Decimal("1000000")
    return (Decimal(prompt_tokens) * input_rate / million) + (
        Decimal(completion_tokens) * output_rate / million
    )


@router.post("/cost-event", status_code=201)
async def ingest_cost_event(request: Request, event: CostEvent):
    check_scopes(request, "cost.report")

    pool = get_pool()
    trace_id = getattr(request.state, "trace_id", None)

    # Pricing lookup - graceful degradation
    pricing = await _lookup_pricing(pool, event.provider, event.model, date.today())
    if pricing:
        cost_usd = _calculate_cost(
            pricing, event.prompt_tokens, event.completion_tokens
        )
    else:
        cost_usd = Decimal("0")
        logger.warning(
            "PRICING_MISS provider=%s model=%s - cost_usd=0",
            event.provider,
            event.model,
        )

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT set_config('rls.role', 'platform_admin', true)")
            row = await conn.fetchrow(
                """
                INSERT INTO alpha_cloud_costs
                    (provider, model, prompt_tokens, completion_tokens, total_tokens,
                     cost_usd, session_type, key_name, intent,
                     executor, on_behalf_of, source_request_id, schema_version,
                     idempotency_key)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12, 1, $13)
                ON CONFLICT (idempotency_key) WHERE idempotency_key IS NOT NULL DO NOTHING
                RETURNING id, cost_usd, created_at
                """,
                event.provider,
                event.model,
                event.prompt_tokens,
                event.completion_tokens,
                event.total_tokens,
                cost_usd,
                event.session_type,
                event.key_name,
                event.intent,
                event.executor,
                event.on_behalf_of,
                trace_id,
                event.idempotency_key,
            )

    if row is None:
        # Idempotency key collision — row already exists, silent no-op
        logger.info(
            "cost_event dedup provider=%s model=%s idempotency_key=%s",
            event.provider,
            event.model,
            event.idempotency_key,
        )
        return {
            "id": None,
            "cost_usd": 0.0,
            "pricing_found": pricing is not None,
            "created_at": None,
            "deduped": True,
        }

    return {
        "id": str(row["id"]),
        "cost_usd": float(row["cost_usd"]),
        "pricing_found": pricing is not None,
        "created_at": row["created_at"].isoformat(),
        "deduped": False,
    }
