"""TraceIdMiddleware — generates a trace_id for every incoming request."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from brain.config.logging_config import new_trace_id


class TraceIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        tid = new_trace_id()
        response: Response = await call_next(request)
        response.headers["X-Trace-Id"] = tid
        return response
