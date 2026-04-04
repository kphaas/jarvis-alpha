import time
from collections import defaultdict, deque
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from brain.config.logging_config import get_logger

logger = get_logger("alpha_brain")

WINDOW_SECONDS = 60
MAX_REQUESTS = 100
BYPASS_PATHS = {"/health", "/v1/health", "/docs", "/openapi.json"}

_request_log: dict[str, deque] = defaultdict(deque)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Sliding window rate limit: 100 req/min per user_id.
    Returns 429 with Retry-After header on breach.
    """

    async def dispatch(self, request: Request, call_next):
        if request.url.path in BYPASS_PATHS:
            return await call_next(request)

        user_id = getattr(request.state, "user_id", "anonymous")
        now = time.time()
        window_start = now - WINDOW_SECONDS
        log = _request_log[user_id]

        while log and log[0] < window_start:
            log.popleft()

        if len(log) >= MAX_REQUESTS:
            retry_after = int(WINDOW_SECONDS - (now - log[0]))
            logger.warning(
                "rate_limit: breached — user_id=%s count=%d", user_id, len(log)
            )
            return JSONResponse(
                status_code=429,
                content={
                    "error": "rate_limit_exceeded",
                    "retry_after_seconds": retry_after,
                },
                headers={"Retry-After": str(retry_after)},
            )

        log.append(now)
        return await call_next(request)
