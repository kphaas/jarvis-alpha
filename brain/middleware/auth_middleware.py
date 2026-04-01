import logging
import base64
import json
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger("jarvis.auth")

BYPASS_PATHS = {"/health", "/v1/health", "/docs", "/openapi.json"}


class AuthMiddleware(BaseHTTPMiddleware):
    """
    Alpha-1 stub: extracts JWT, parses sub claim, sets request.state.user_id.
    Does NOT reject requests — logs warnings only. Full enforcement in Alpha-2.
    """

    async def dispatch(self, request: Request, call_next):
        if request.url.path in BYPASS_PATHS:
            request.state.user_id = "anonymous"
            return await call_next(request)

        user_id = "anonymous"
        auth_header = request.headers.get("Authorization", "")

        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            try:
                payload_b64 = token.split(".")[1]
                padding = 4 - len(payload_b64) % 4
                payload_b64 += "=" * padding
                payload = json.loads(base64.urlsafe_b64decode(payload_b64))
                user_id = payload.get("sub", "anonymous")
                logger.debug(
                    "auth_middleware: user_id=%s path=%s", user_id, request.url.path
                )
            except Exception as e:
                logger.warning(
                    "auth_middleware: JWT parse failed — %s — path=%s",
                    e,
                    request.url.path,
                )
        else:
            logger.warning(
                "auth_middleware: no Bearer token — path=%s", request.url.path
            )

        request.state.user_id = user_id
        return await call_next(request)
