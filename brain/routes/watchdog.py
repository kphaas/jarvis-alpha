"""
watchdog.py - Watchdog events API.

Read endpoints (GET):
  /v1/watchdog/events    - list events with filters
  /v1/watchdog/status    - latest state per service

Write endpoint (POST) - NEW 2026-04-07:
  /v1/watchdog/event     - ingest event from a remote watchdog (Pattern B)

Pattern B: each node runs its own local watchdog. Brain centrally observes
via this ingest endpoint, NOT by polling each node directly.

Scope required for POST: watchdog.events.ingest (or admin role)
RLS write policy on alpha_watchdog_events requires rls.user_id = 'system'
which is set inside the transaction in ingest_event().
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from brain.db.pool import get_pool
from brain.middleware.scopes import check_scopes

router = APIRouter(prefix="/v1/watchdog", tags=["watchdog"])


# ─── Models ──────────────────────────────────────────────────────────────────


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


# Allowed event types from the alpha_watchdog_events CHECK constraint
ALLOWED_EVENT_TYPES = {
    "down",
    "restored",
    "degraded",
    "restart_triggered",
    "restart_succeeded",
    "restart_failed",
    "check_error",
}


class WatchdogEventIngest(BaseModel):
    """Payload from a remote watchdog (e.g., Sandbox forge_watchdog.py)."""

    service_name: str = Field(..., min_length=1, max_length=128)
    node: str = Field(..., min_length=1, max_length=64)
    event_type: str = Field(..., min_length=1, max_length=32)
    previous_state: str | None = None
    current_state: str | None = None
    consecutive_failures: int = Field(default=0, ge=0)
    latency_ms: float | None = None
    http_status: int | None = None
    error_message: str | None = None
    action_taken: str | None = None
    trace_id: str | None = None  # UUID string from caller


class WatchdogEventIngestResponse(BaseModel):
    id: str
    accepted: bool


# ─── GET /v1/watchdog/events ─────────────────────────────────────────────────


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


# ─── GET /v1/watchdog/status ─────────────────────────────────────────────────


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


# ─── POST /v1/watchdog/event (NEW 2026-04-07) ────────────────────────────────


@router.post("/event", response_model=WatchdogEventIngestResponse, status_code=201)
async def ingest_event(
    request: Request,
    body: WatchdogEventIngest,
) -> WatchdogEventIngestResponse:
    """Ingest a watchdog event from a remote node (Pattern B).

    Used by Sandbox's forge_watchdog.py and any other per-node watchdogs
    that report into Brain's centralized observability table.

    Required scope: watchdog.events.ingest
    Admin users (actor_type=user, role=admin) bypass scope check.
    """
    check_scopes(request, "watchdog.events.ingest")

    if body.event_type not in ALLOWED_EVENT_TYPES:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "invalid event_type",
                "allowed": sorted(ALLOWED_EVENT_TYPES),
                "received": body.event_type,
            },
        )

    pool = get_pool()
    async with pool.acquire() as conn:
        # The RLS write policy requires rls.user_id = 'system'.
        # set_config(..., true) is transaction-local, so we need conn.transaction().
        async with conn.transaction():
            await conn.execute("SELECT set_config('rls.user_id', 'system', true)")

            row = await conn.fetchrow(
                """
                INSERT INTO alpha_watchdog_events (
                    service_name,
                    node,
                    event_type,
                    previous_state,
                    current_state,
                    consecutive_failures,
                    latency_ms,
                    http_status,
                    error_message,
                    action_taken,
                    trace_id
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::uuid)
                RETURNING id::text
                """,
                body.service_name,
                body.node,
                body.event_type,
                body.previous_state,
                body.current_state,
                body.consecutive_failures,
                body.latency_ms,
                body.http_status,
                body.error_message,
                body.action_taken,
                body.trace_id,
            )

    return WatchdogEventIngestResponse(
        id=row["id"],
        accepted=True,
    )
