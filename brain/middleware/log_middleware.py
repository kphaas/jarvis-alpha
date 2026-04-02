import time
import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from brain.db.pool import get_pool


class LogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        trace_id = uuid.uuid4()
        start = time.monotonic()

        response = await call_next(request)

        latency_ms = int((time.monotonic() - start) * 1000)
        user_id = getattr(request.state, "user_id", "anonymous")
        workspace_id = getattr(request.state, "workspace_id", None)

        try:
            pool = get_pool()
        except RuntimeError:
            pool = None

        if pool:
            try:
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO jarvis_request_log
                          (trace_id, workspace_id, user_id, node,
                           route, method, status_code, latency_ms)
                        VALUES ($1,$2,$3,'brain',$4,$5,$6,$7)
                        """,
                        trace_id,
                        workspace_id,
                        user_id,
                        request.url.path,
                        request.method,
                        response.status_code,
                        latency_ms,
                    )
            except Exception:
                pass

        return response
