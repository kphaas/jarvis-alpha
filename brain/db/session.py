from contextlib import asynccontextmanager

from brain.db.pool import get_pool


@asynccontextmanager
async def get_db(user_id: str):
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT set_config('jarvis.current_user', $1, true)",
                user_id,
            )
            yield conn
