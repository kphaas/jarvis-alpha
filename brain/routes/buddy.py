from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from brain.db.rls import rls_connection

router = APIRouter(prefix="/v1/buddy", tags=["buddy"])


class BuddyEvent(BaseModel):
    id: str
    user_id: str | None
    event_type: str
    title: str
    body: str | None
    priority: int
    read: bool
    created_at: str


class BuddyEventsResponse(BaseModel):
    events: list[BuddyEvent]
    unread_count: int


def _principal_buddy_user_id(request: Request, requested_user_id: str | None) -> str:
    principal_user_id = str(getattr(request.state, "user_id", "") or "").strip()
    if not principal_user_id or principal_user_id == "unknown":
        raise HTTPException(status_code=401, detail="Unauthorized")

    if requested_user_id is None:
        return principal_user_id

    requested = requested_user_id.strip()
    if requested and requested != principal_user_id:
        raise HTTPException(status_code=403, detail="buddy_user_mismatch")
    return principal_user_id


@router.get("/events", response_model=BuddyEventsResponse)
async def get_events(
    request: Request,
    user_id: str | None = Query(default=None),
    limit: int = Query(default=20, le=100),
    unread_only: bool = Query(default=False),
) -> BuddyEventsResponse:
    principal_user_id = _principal_buddy_user_id(request, user_id)
    async with rls_connection(request) as conn:
        where = "WHERE (user_id = $1 OR user_id IS NULL)"
        if unread_only:
            where += " AND read = false"

        events = await conn.fetch(
            f"""
            SELECT id::text, user_id, event_type, title,
                   body, priority, read,
                   created_at::text
            FROM alpha_buddy_events
            {where}
            ORDER BY created_at DESC
            LIMIT $2
            """,
            principal_user_id,
            limit,
        )

        unread = await conn.fetchval(
            """
            SELECT COUNT(*) FROM alpha_buddy_events
            WHERE (user_id = $1 OR user_id IS NULL)
              AND read = false
            """,
            principal_user_id,
        )

    return BuddyEventsResponse(
        events=[BuddyEvent(**dict(e)) for e in events],
        unread_count=unread or 0,
    )


@router.post("/events/{event_id}/read")
async def mark_read(event_id: str, request: Request) -> dict:
    principal_user_id = _principal_buddy_user_id(request, None)
    async with rls_connection(request) as conn:
        marked_id = await conn.fetchval(
            """
            UPDATE alpha_buddy_events
            SET read = true
            WHERE id = $1::uuid
              AND (user_id = $2 OR user_id IS NULL)
            RETURNING id::text
            """,
            event_id,
            principal_user_id,
        )
    if marked_id is None:
        raise HTTPException(status_code=404, detail="buddy_event_not_found")
    return {"marked_read": marked_id}


@router.post("/events/read-all")
async def mark_all_read(
    request: Request,
    user_id: str | None = Query(default=None),
) -> dict:
    principal_user_id = _principal_buddy_user_id(request, user_id)
    async with rls_connection(request) as conn:
        await conn.execute(
            """
            UPDATE alpha_buddy_events SET read = true
            WHERE user_id = $1 OR user_id IS NULL
            """,
            principal_user_id,
        )
    return {"marked_all_read": True, "user_id": principal_user_id}
