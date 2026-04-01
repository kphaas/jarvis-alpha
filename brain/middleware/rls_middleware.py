import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from brain.db.session import get_raw_connection

logger = logging.getLogger("jarvis.rls")

BYPASS_PATHS = {"/health", "/v1/health", "/docs", "/openapi.json"}


class RLSContextMiddleware(BaseHTTPMiddleware):
    """
    Sets jarvis.current_user in Postgres session after auth sets request.state.user_id.
    Must run AFTER AuthMiddleware in the stack.
    """

    async def dispatch(self, request: Request, call_next):
        if request.url.path in BYPASS_PATHS:
            return await call_next(request)

        user_id = getattr(request.state, "user_id", "anonymous")

        try:
            async with get_raw_connection() as conn:
                if conn is None:
                    logger.debug("rls_middleware: stub connection, skip SET LOCAL")
                else:
                    await conn.execute(f"SET LOCAL jarvis.current_user = '{user_id}'")
                    logger.debug(
                        "rls_middleware: SET LOCAL jarvis.current_user=%s", user_id
                    )
        except Exception as e:
            logger.error("rls_middleware: failed to set RLS context — %s", e)

        return await call_next(request)
