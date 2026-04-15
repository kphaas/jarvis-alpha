from __future__ import annotations

from fastapi import APIRouter, Query, Request
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


@router.get("/events", response_model=BuddyEventsResponse)
async def get_events(
    request: Request,
    user_id: str = Query(default="anon"),
    limit: int = Query(default=20, le=100),
    unread_only: bool = Query(default=False),
) -> BuddyEventsResponse:
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
            user_id,
            limit,
        )

        unread = await conn.fetchval(
            """
            SELECT COUNT(*) FROM alpha_buddy_events
            WHERE (user_id = $1 OR user_id IS NULL)
              AND read = false
            """,
            user_id,
        )

    return BuddyEventsResponse(
        events=[BuddyEvent(**dict(e)) for e in events],
        unread_count=unread or 0,
    )


@router.post("/events/{event_id}/read")
async def mark_read(event_id: str, request: Request) -> dict:
    async with rls_connection(request) as conn:
        await conn.execute(
            "UPDATE alpha_buddy_events SET read = true WHERE id = $1::uuid",
            event_id,
        )
    return {"marked_read": event_id}


@router.post("/events/read-all")
async def mark_all_read(request: Request, user_id: str = Query(default="anon")) -> dict:
    async with rls_connection(request) as conn:
        await conn.execute(
            """
            UPDATE alpha_buddy_events SET read = true
            WHERE user_id = $1 OR user_id IS NULL
            """,
            user_id,
        )
    return {"marked_all_read": True, "user_id": user_id}
