from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class RLSMiddleware(BaseHTTPMiddleware):
    """
    RLS session variable is set per DB transaction in brain.db.session.get_db.
    Placeholder in the middleware stack (runs after AuthMiddleware).
    """

    async def dispatch(self, request: Request, call_next):
        return await call_next(request)


RLSContextMiddleware = RLSMiddleware
