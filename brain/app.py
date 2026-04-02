from contextlib import asynccontextmanager
from fastapi import FastAPI
from brain.middleware.auth_middleware import AuthMiddleware
from brain.middleware.rls_middleware import RLSMiddleware
from brain.middleware.rate_limit_middleware import RateLimitMiddleware
from brain.middleware.log_middleware import LogMiddleware
from brain.db.pool import init_pool, close_pool, get_pool
from brain.core.config import ALPHA_DB_DSN
from brain.routes.ask import router as ask_router
from brain.routes.chat import router as chat_router
from brain.routes.memory import router as memory_router
from brain.routes.vault import router as vault_router
from brain.routes.buddy import router as buddy_router
from brain.middleware.jwt_auth import JWTAuthMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pool(ALPHA_DB_DSN)
    yield
    await close_pool()


app = FastAPI(title="jarvis-alpha", version="0.1.0", lifespan=lifespan)

app.add_middleware(LogMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(RLSMiddleware)
app.add_middleware(AuthMiddleware)
app.add_middleware(JWTAuthMiddleware)

app.include_router(ask_router)
app.include_router(chat_router)
app.include_router(memory_router)
app.include_router(vault_router)
app.include_router(buddy_router)


@app.get("/health")
async def health():
    db_ok = False
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        db_ok = True
    except Exception:
        db_ok = False
    return {
        "status": "ok" if db_ok else "degraded",
        "service": "jarvis-alpha-brain",
        "db": "ok" if db_ok else "error",
        "version": "0.1.0",
    }
