from contextlib import asynccontextmanager
import asyncio
from fastapi import FastAPI
from jarvis_common.logging_config import get_logger
from gateway.routes.admin import admin_router
from gateway.routes.cloud_routes import router as cloud_router
from gateway.routes.unifi import router as unifi_router
from gateway.cost_emitter import flush_loop

logger = get_logger("alpha_gateway")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("jarvis-alpha gateway starting — pure adapter mode")
    flush_task = asyncio.create_task(flush_loop())
    yield
    flush_task.cancel()
    try:
        await flush_task
    except asyncio.CancelledError:
        pass
    logger.info("jarvis-alpha gateway shutdown")


app = FastAPI(title="jarvis-alpha gateway", version="alpha-1", lifespan=lifespan)
app.include_router(cloud_router)
app.include_router(unifi_router)
app.include_router(admin_router)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "node": "gateway",
        "version": "alpha-1",
        "mode": "pure-adapter",
    }
