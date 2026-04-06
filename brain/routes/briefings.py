from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any, Literal

import asyncpg
from asyncpg.exceptions import UniqueViolationError
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, field_validator

from brain.db.pool import get_pool
from brain.middleware.jwt_auth import require_auth
from brain.middleware.scopes import check_scopes

router = APIRouter(prefix="/v1/briefings", tags=["briefings"])

BATCH_RUN_ID_RE = re.compile(r"^[0-9]{8}_[0-9]{4}_[a-f0-9]{4}$")


def _parse_jsonb(value: Any) -> Any:
    """asyncpg returns JSONB as string — parse if needed."""
    if value is None:
        return None
    if isinstance(value, str):
        return json.loads(value)
    return value


def _check_read_scope(request: Request) -> None:
    """Check briefings.read scope or admin wildcard."""
    check_scopes(request, "briefings.read")


class BriefingIngest(BaseModel):
    batch_run_id: str
    briefing_date: date
    started_at: datetime
    source: Literal["forge_overnight", "forge_manual", "forge_ci", "buddy_alert"]
    summary: dict[str, Any]
    results: list[dict[str, Any]]
    markdown: str | None = None

    @field_validator("batch_run_id")
    @classmethod
    def validate_batch_run_id(cls, v: str) -> str:
        if not BATCH_RUN_ID_RE.match(v):
            raise ValueError("batch_run_id must match YYYYMMDD_HHMM_xxxx (4 hex chars)")
        return v


class BriefingIngestResponse(BaseModel):
    id: int
    batch_run_id: str


class BriefingFull(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    batch_run_id: str
    briefing_date: date
    started_at: datetime
    source: str
    summary: dict[str, Any]
    results: list[Any]
    markdown: str | None
    created_at: datetime | None


class BriefingListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    batch_run_id: str
    briefing_date: date
    started_at: datetime
    source: str
    summary: dict[str, Any]
    created_at: datetime | None


class BriefingListResponse(BaseModel):
    briefings: list[BriefingListItem]
    total: int
    limit: int
    offset: int


def _record_to_full(row: asyncpg.Record) -> BriefingFull:
    return BriefingFull(
        id=row["id"],
        batch_run_id=row["batch_run_id"],
        briefing_date=row["briefing_date"],
        started_at=row["started_at"],
        source=row["source"],
        summary=_parse_jsonb(row["summary"]) or {},
        results=_parse_jsonb(row["results"]) or [],
        markdown=row["markdown"],
        created_at=row["created_at"],
    )


def _record_to_list_item(row: asyncpg.Record) -> BriefingListItem:
    return BriefingListItem(
        id=row["id"],
        batch_run_id=row["batch_run_id"],
        briefing_date=row["briefing_date"],
        started_at=row["started_at"],
        source=row["source"],
        summary=_parse_jsonb(row["summary"]) or {},
        created_at=row["created_at"],
    )


@router.post("/ingest", status_code=201, response_model=BriefingIngestResponse)
async def ingest_briefing(
    request: Request, body: BriefingIngest
) -> BriefingIngestResponse:
    check_scopes(request, "forge.briefings.ingest")
    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO alpha_briefings (
                    batch_run_id, briefing_date, started_at, source,
                    summary, results, markdown
                )
                VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7)
                RETURNING id, batch_run_id
                """,
                body.batch_run_id,
                body.briefing_date,
                body.started_at,
                body.source,
                json.dumps(body.summary),
                json.dumps(body.results),
                body.markdown,
            )
    except UniqueViolationError:
        raise HTTPException(
            status_code=409,
            detail="Briefing with this batch_run_id already exists",
        ) from None
    assert row is not None
    return BriefingIngestResponse(id=row["id"], batch_run_id=row["batch_run_id"])


@router.get("/latest", response_model=BriefingFull)
async def get_latest_briefing(
    request: Request,
    _: str = Depends(require_auth),
    source: str | None = Query(default=None),
) -> BriefingFull:
    _check_read_scope(request)
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, batch_run_id, briefing_date, started_at, source,
                   summary, results, markdown, created_at
            FROM alpha_briefings
            WHERE ($1::text IS NULL OR source = $1)
            ORDER BY started_at DESC
            LIMIT 1
            """,
            source,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="No briefings found")
    return _record_to_full(row)


@router.get("", response_model=BriefingListResponse)
async def list_briefings(
    request: Request,
    _: str = Depends(require_auth),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    source: str | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
) -> BriefingListResponse:
    _check_read_scope(request)
    pool = get_pool()
    conditions: list[str] = []
    params: list[Any] = []

    def add(cond: str, *vals: Any) -> None:
        conditions.append(cond)
        params.extend(vals)

    if source is not None:
        add(f"source = ${len(params) + 1}", source)
    if date_from is not None:
        add(f"briefing_date >= ${len(params) + 1}", date_from)
    if date_to is not None:
        add(f"briefing_date <= ${len(params) + 1}", date_to)

    where_sql = " AND ".join(conditions) if conditions else "TRUE"
    n = len(params)
    lim_ph, off_ph = f"${n + 1}", f"${n + 2}"
    list_params = [*params, limit, offset]

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT id, batch_run_id, briefing_date, started_at, source,
                   summary, created_at
            FROM alpha_briefings
            WHERE {where_sql}
            ORDER BY started_at DESC
            LIMIT {lim_ph} OFFSET {off_ph}
            """,
            *list_params,
        )
        total = await conn.fetchval(
            f"SELECT COUNT(*)::bigint FROM alpha_briefings WHERE {where_sql}",
            *params,
        )

    return BriefingListResponse(
        briefings=[_record_to_list_item(r) for r in rows],
        total=int(total or 0),
        limit=limit,
        offset=offset,
    )


@router.get("/{batch_run_id}", response_model=BriefingFull)
async def get_briefing_by_batch_run_id(
    batch_run_id: str,
    request: Request,
    _: str = Depends(require_auth),
) -> BriefingFull:
    _check_read_scope(request)
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, batch_run_id, briefing_date, started_at, source,
                   summary, results, markdown, created_at
            FROM alpha_briefings
            WHERE batch_run_id = $1
            """,
            batch_run_id,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="Briefing not found")
    return _record_to_full(row)
