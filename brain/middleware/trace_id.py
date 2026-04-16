"""TraceIdMiddleware — generates a trace_id for every incoming request."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from jarvis_common.logging_config import new_trace_id, set_trace_id


class TraceIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        incoming = request.headers.get("X-Trace-Id")
        if incoming:
            tid = incoming
            set_trace_id(tid)
        else:
            tid = new_trace_id()
        request.state.trace_id = tid
        response: Response = await call_next(request)
        response.headers["X-Trace-Id"] = tid
        return response
