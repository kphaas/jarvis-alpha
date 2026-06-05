from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from jarvis_common.logging_config import get_logger
from brain.middleware.rate_limit_middleware import RateLimitMiddleware
from brain.middleware.approval import ApprovalMiddleware
from brain.middleware.log_middleware import LogMiddleware
from brain.middleware.trace_id import TraceIdMiddleware
from brain.middleware.approval_audit import audit_route_classifications
from brain.db.pool import init_pool, close_pool
from brain.core.config import ALPHA_DB_DSN_WRITER
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
from brain.routes.dream import dream_router
from brain.routes.dream_planning import dream_planning_router
from brain.routes.mcp_registry import mcp_router
from brain.routes.prompts import router as prompts_router
from brain.routes.approvals import router as approvals_router
from brain.routes.bridge_approvals import router as bridge_approvals_router
from brain.routes.watchdog import router as watchdog_router
from brain.routes.briefings import router as briefings_router
from brain.routes.school_email import router as school_email_router
from brain.routes.internal_cost import router as internal_cost_router
from brain.routes.review import router as review_router
from brain.routes.registry import router as registry_router
from brain.routes.chatops import router as chatops_router
from brain.routes.spark_drafts import router as spark_drafts_router
from brain.routes.spark_imessage import router as spark_imessage_router
from brain.routes.privacy import router as privacy_router
from brain.middleware.jwt_auth import JWTAuthMiddleware

logger = get_logger("alpha_brain")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db_pool = await init_pool(ALPHA_DB_DSN_WRITER)
    logger.info("FastAPI DB pool initialized on writer role (Stage 5b)")
    await recover_stuck_graphs(db_pool)
    audit_route_classifications(app)
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
app.add_middleware(ApprovalMiddleware)
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
app.include_router(dream_router)
app.include_router(dream_planning_router)
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
app.include_router(prompts_router)
app.include_router(approvals_router)
app.include_router(bridge_approvals_router)
app.include_router(watchdog_router)
app.include_router(briefings_router)
app.include_router(school_email_router)
app.include_router(internal_cost_router)
app.include_router(review_router)
app.include_router(registry_router)
app.include_router(chatops_router)
app.include_router(spark_drafts_router)
app.include_router(spark_imessage_router)
app.include_router(privacy_router)

# TD-107 test 2 — validating restart-path fires on brain/*.py changes (Apr 18)
