from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from jarvis_common.logging_config import get_logger
from brain.middleware.auth_middleware import AuthMiddleware
from brain.middleware.rls_middleware import RLSMiddleware
from brain.middleware.rate_limit_middleware import RateLimitMiddleware
from brain.middleware.log_middleware import LogMiddleware
from brain.middleware.trace_id import TraceIdMiddleware
from brain.db.pool import init_pool, close_pool
from brain.core.config import ALPHA_DB_DSN
from brain.tasks.executor import recover_stuck_graphs
from brain.routes.ask import router as ask_router
from brain.routes.chat import router as chat_router
from brain.routes.memory import router as memory_router
from brain.routes.vault import router as vault_router
from brain.routes.buddy import router as buddy_router
from brain.routes.home import router as home_router
from brain.routes.mesh import router as mesh_router
from brain.routes.unifi import router as unifi_router
from brain.routes.pin_auth import router as pin_auth_router
from brain.routes.health import router as health_router
from brain.routes.logs import logs_router
from brain.routes.diagnose import diagnose_router
from brain.routes.patterns import patterns_router
from brain.routes.tasks import tasks_router
from brain.routes.costs import router as costs_router
from brain.routes.dev import dev_router
from brain.routes.metrics import router as metrics_router
from brain.routes.rotation import rotation_router
from brain.routes.security import security_router
from brain.routes.honeypot import honeypot_router
from brain.routes.mcp_registry import mcp_router
from brain.middleware.jwt_auth import JWTAuthMiddleware

logger = get_logger("alpha_brain")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db_pool = await init_pool(ALPHA_DB_DSN)
    await recover_stuck_graphs(db_pool)
    # Secret audit trail
    import asyncio

    from brain.audit.secret_audit import audit_hook, ensure_table, init_audit
    from jarvis_common.secrets import register_audit_hook

    await ensure_table()
    init_audit(asyncio.get_running_loop())
    register_audit_hook(audit_hook)
    from jarvis_common.secrets import clear_cache

    clear_cache()
    logger.info("secret cache cleared — next access will trigger audit")
    logger.info("secret audit hook registered")
    yield
    await close_pool()


app = FastAPI(title="jarvis-alpha", version="0.1.0", lifespan=lifespan)

app.add_middleware(LogMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(RLSMiddleware)
app.add_middleware(AuthMiddleware)
app.add_middleware(JWTAuthMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://jarvis-endpoint.tail40ed36.ts.net:4100"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(TraceIdMiddleware)

app.include_router(pin_auth_router)
app.include_router(health_router)
app.include_router(honeypot_router)
app.include_router(logs_router)
app.include_router(diagnose_router)
app.include_router(patterns_router)
app.include_router(tasks_router)
app.include_router(ask_router)
app.include_router(chat_router)
app.include_router(memory_router)
app.include_router(vault_router)
app.include_router(buddy_router)
app.include_router(home_router)
app.include_router(mesh_router)
app.include_router(unifi_router)
app.include_router(costs_router)
app.include_router(dev_router)
app.include_router(metrics_router)
app.include_router(security_router)
app.include_router(mcp_router)
app.include_router(rotation_router)
