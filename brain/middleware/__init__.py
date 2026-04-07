"""
brain.middleware — canonical list of available middlewares.

Middleware order in app.py (LIFO add order, FIFO request order):
    TraceIdMiddleware       — generates trace_id, sets X-Trace-Id header
    CORSMiddleware          — origin enforcement (Endpoint only)
    JWTAuthMiddleware       — RS256 JWT verification, populates request.state
    ApprovalMiddleware      — risk-tier classification, approval gating
    RateLimitMiddleware     — per-user rate limiting
    LogMiddleware           — structured access logging

Note: RLS context is set per-connection in brain.db.rls.rls_connection(),
not via middleware. There is intentionally no RLSMiddleware.
"""

from .approval import ApprovalMiddleware
from .jwt_auth import JWTAuthMiddleware
from .log_middleware import LogMiddleware
from .rate_limit_middleware import RateLimitMiddleware
from .trace_id import TraceIdMiddleware

__all__ = [
    "ApprovalMiddleware",
    "JWTAuthMiddleware",
    "LogMiddleware",
    "RateLimitMiddleware",
    "TraceIdMiddleware",
]
