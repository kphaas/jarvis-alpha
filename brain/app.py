import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from brain.middleware import AuthMiddleware, RLSContextMiddleware, RateLimitMiddleware

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
)
logger = logging.getLogger("jarvis.alpha.brain")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("jarvis-alpha brain starting")
    yield
    logger.info("jarvis-alpha brain shutdown")


app = FastAPI(title="jarvis-alpha brain", version="alpha-1", lifespan=lifespan)

app.add_middleware(RateLimitMiddleware)
app.add_middleware(RLSContextMiddleware)
app.add_middleware(AuthMiddleware)


@app.get("/health")
async def health():
    return {"status": "ok", "node": "brain", "version": "alpha-1"}


@app.get("/v1/health")
async def health_v1():
    return {
        "status": "ok",
        "node": "brain",
        "version": "alpha-1",
        "middleware": ["auth", "rls", "rate_limit"],
    }
