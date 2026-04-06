"""
watchdog.py — Read-only API for watchdog events.
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel

from brain.db.pool import get_pool

router = APIRouter(prefix="/v1/watchdog", tags=["watchdog"])


class WatchdogEvent(BaseModel):
    id: str
    service_name: str
    node: str
    event_type: str
    previous_state: str | None
    current_state: str | None
    consecutive_failures: int
    latency_ms: float | None
    http_status: int | None
    error_message: str | None
    action_taken: str | None
    created_at: str


class WatchdogEventsResponse(BaseModel):
    events: list[WatchdogEvent]
    total: int


class ServiceStatus(BaseModel):
    service_name: str
    node: str
    current_state: str
    last_event_at: str
    consecutive_failures: int


class WatchdogStatusResponse(BaseModel):
    services: list[ServiceStatus]
    checked_at: str


@router.get("/events", response_model=WatchdogEventsResponse)
async def get_events(
    limit: int = Query(default=50, le=500),
    event_type: str | None = Query(default=None),
    service_name: str | None = Query(default=None),
) -> WatchdogEventsResponse:
    pool = get_pool()

    filters = []
    params: list = []
    idx = 1

    if event_type:
        filters.append(f"event_type = ${idx}")
        params.append(event_type)
        idx += 1

    if service_name:
        filters.append(f"service_name = ${idx}")
        params.append(service_name)
        idx += 1

    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    params.append(limit)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT
                id::text,
                service_name,
                node,
                event_type,
                previous_state,
                current_state,
                consecutive_failures,
                latency_ms::float,
                http_status,
                error_message,
                action_taken,
                created_at::text
            FROM alpha_watchdog_events
            {where}
            ORDER BY created_at DESC
            LIMIT ${idx}
            """,
            *params,
        )

        total = await conn.fetchval(
            f"SELECT COUNT(*) FROM alpha_watchdog_events {where}",
            *params[:-1],
        )

    return WatchdogEventsResponse(
        events=[WatchdogEvent(**dict(r)) for r in rows],
        total=total or 0,
    )


@router.get("/status", response_model=WatchdogStatusResponse)
async def get_status() -> WatchdogStatusResponse:
    pool = get_pool()

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT ON (service_name)
                service_name,
                node,
                current_state,
                created_at::text AS last_event_at,
                consecutive_failures
            FROM alpha_watchdog_events
            ORDER BY service_name, created_at DESC
            """
        )

        checked_at = await conn.fetchval("SELECT now()::text")

    return WatchdogStatusResponse(
        services=[ServiceStatus(**dict(r)) for r in rows],
        checked_at=checked_at or "",
    )
