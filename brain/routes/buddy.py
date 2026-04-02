from __future__ import annotations

from fastapi import APIRouter, Query

from brain.db.pool import get_pool

router = APIRouter(prefix="/v1/buddy", tags=["buddy"])


@router.post("/events/{event_id}/read")
async def mark_read(event_id: str) -> dict:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE alpha_buddy_events SET read = true WHERE id = $1::uuid",
            event_id,
        )
    return {"marked_read": event_id}


@router.post("/events/read-all")
async def mark_all_read(user_id: str = Query(default="anon")) -> dict:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE alpha_buddy_events SET read = true
            WHERE user_id = $1 OR user_id IS NULL
            """,
            user_id,
        )
    return {"marked_all_read": True, "user_id": user_id}
