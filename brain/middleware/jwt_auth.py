import os
import logging
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import jwt

logger = logging.getLogger(__name__)

SKIP_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}


def _load_public_key() -> bytes:
    path = os.environ.get("ALPHA_JWT_PUBLIC_KEY_PATH", "")
    if not path:
        raise RuntimeError("ALPHA_JWT_PUBLIC_KEY_PATH not set")
    with open(path, "rb") as f:
        return f.read()


class JWTAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self._public_key = _load_public_key()

    async def dispatch(self, request: Request, call_next):
        if request.url.path in SKIP_PATHS:
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(status_code=401, content={"error": "Missing token"})

        token = auth_header.removeprefix("Bearer ").strip()
        try:
            payload = jwt.decode(token, self._public_key, algorithms=["RS256"])
            request.state.user_id = payload.get("sub", "unknown")
            request.state.role = payload.get("role", "user")
        except jwt.ExpiredSignatureError:
            return JSONResponse(status_code=401, content={"error": "Token expired"})
        except jwt.InvalidTokenError as e:
            logger.warning(f"JWT validation failed: {e}")
            return JSONResponse(status_code=401, content={"error": "Invalid token"})

        return await call_next(request)
