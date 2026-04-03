from collections.abc import AsyncGenerator

import asyncpg

from brain.db.pool import get_pool


async def get_db() -> AsyncGenerator[asyncpg.Connection, None]:
    pool = get_pool()
    async with pool.acquire() as conn:
        yield conn
