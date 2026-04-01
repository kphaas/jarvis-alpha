import asyncpg
from contextlib import asynccontextmanager
from brain.core.secrets import get_secret

_pool: asyncpg.Pool | None = None


async def init_pool() -> None:
    global _pool
    dsn = get_secret("ALPHA_DB_DSN")
    _pool = await asyncpg.create_pool(
        dsn=dsn,
        min_size=2,
        max_size=10,
        command_timeout=30,
    )


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


@asynccontextmanager
async def get_db(user_id: str):
    assert _pool is not None, "DB pool not initialised"
    async with _pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT set_config('jarvis.current_user', $1, true)",
                user_id,
            )
            yield conn
