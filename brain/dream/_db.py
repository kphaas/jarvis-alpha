"""Activity-scoped DB connection helper for Dream Mode Temporal activities.

Activities run in a Temporal worker process (not FastAPI), so they cannot
use brain.db.rls.rls_connection() which requires a FastAPI Request object.

Pattern matches the current Dream route write path: acquire the writer pool
connection, set transaction-scoped rls.user_id + rls.role GUCs, yield.

Deferred (TD-145): replace with SECURITY DEFINER functions in Alpha-6.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

import asyncpg

from brain.db.pool import get_pool


@asynccontextmanager
async def activity_db(
    user_id: str = "system",
    role: str = "platform_admin",
) -> AsyncIterator[asyncpg.Connection]:
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT set_config('rls.user_id', $1, true)", user_id)
            await conn.execute("SELECT set_config('rls.role', $1, true)", role)
            yield conn
