import os
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import jwt

from jarvis_common.logging_config import get_logger

logger = get_logger("alpha_brain")

ALPHA_SESSION_COOKIE = "alpha_session"
ALPHA_REVOKED_JTIS_ENV = "ALPHA_REVOKED_JTIS"
USER_ISSUER = "user"

# Issuer → public key mapping
# "user" is the PIN-authenticated user issuer.
_KEY_REGISTRY: dict[str, Path] = {}


def _build_key_registry() -> dict[str, Path]:
    """Build issuer → public key path mapping at startup."""
    registry = {}

    # User key (existing — backward compatible)
    user_key = Path(os.path.dirname(__file__)).parent / "pki" / "jwt_public.pem"
    if user_key.exists():
        registry[USER_ISSUER] = user_key

    # Service keys
    services_dir = Path.home() / "jarvis" / "pki" / "services"
    if services_dir.is_dir():
        for pem in services_dir.glob("*_public.pem"):
            issuer = pem.stem.replace("_public", "")
            registry[issuer] = pem

    return registry


def _get_public_key(iss: str | None) -> str:
    """Look up the public key for a given issuer."""
    global _KEY_REGISTRY
    if not _KEY_REGISTRY:
        _KEY_REGISTRY = _build_key_registry()

    if not iss:
        raise ValueError("Missing issuer claim")

    if iss not in _KEY_REGISTRY:
        raise ValueError(f"No public key found for issuer: {iss}")

    return _KEY_REGISTRY[iss].read_text()


def _allowed_actor_types(iss: str) -> frozenset[str]:
    if iss == USER_ISSUER:
        return frozenset({"user"})
    return frozenset({"service"})


def _validate_issuer_actor_binding(payload: dict[str, object]) -> None:
    iss = payload.get("iss")
    actor_type = payload.get("actor_type")

    if not isinstance(iss, str) or not iss:
        raise ValueError("Missing issuer claim")
    if not isinstance(actor_type, str) or not actor_type:
        raise ValueError("Missing actor_type claim")

    allowed = _allowed_actor_types(iss)
    if actor_type not in allowed:
        raise ValueError(
            f"issuer_actor_type_mismatch issuer={iss} actor_type={actor_type}"
        )


def _revoked_jtis() -> set[str]:
    raw = os.environ.get(ALPHA_REVOKED_JTIS_ENV, "")
    return {part.strip() for part in raw.split(",") if part.strip()}


def _validate_jti(payload: dict[str, object]) -> str:
    jti = payload.get("jti")
    if not isinstance(jti, str) or not jti.strip():
        raise ValueError("Missing jti claim")
    if jti in _revoked_jtis():
        raise ValueError(f"revoked_jti {jti}")
    return jti


PUBLIC_HEALTH_PATHS = frozenset({"/health", "/health/ready"})
PUBLIC_AUTH_PATHS = frozenset({"/v1/auth/login-profiles", "/v1/auth/pin"})

# These endpoints intentionally skip JWT because the route verifies its own
# shared secret or incoming platform token before doing any work.
ROUTE_TOKEN_AUTH_PATHS = frozenset(
    {"/v1/chatops/mattermost/command", "/v1/security/sweep-report"}
)
ROUTE_TOKEN_AUTH_PREFIXES = frozenset({"/v1/bridge/"})

# Honeypot traps must be reachable without JWT so scanner traffic can be
# recorded. They should never expose real data or operational controls.
HONEYPOT_PATHS = frozenset(
    {
        "/admin",
        "/wp-login.php",
        "/.env",
        "/.git/config",
        "/phpmyadmin",
        "/phpmyadmin/",
        "/api/v1/debug",
    }
)

SKIP_PATHS = set(
    PUBLIC_HEALTH_PATHS | PUBLIC_AUTH_PATHS | ROUTE_TOKEN_AUTH_PATHS | HONEYPOT_PATHS
)


def require_auth(request: Request) -> str:
    user_id = getattr(request.state, "user_id", None)
    if not user_id or user_id == "unknown":
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user_id


def _request_token(request: Request) -> str | None:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.removeprefix("Bearer ").strip()
        return token or None

    cookie_token = request.cookies.get(ALPHA_SESSION_COOKIE, "").strip()
    return cookie_token or None


class JWTAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)

        if request.url.path in SKIP_PATHS or any(
            request.url.path.startswith(prefix) for prefix in ROUTE_TOKEN_AUTH_PREFIXES
        ):
            return await call_next(request)

        token = _request_token(request)
        if not token:
            return JSONResponse(status_code=401, content={"error": "Missing token"})

        try:
            unverified = jwt.decode(token, options={"verify_signature": False})
            iss = unverified.get("iss")
            public_key = _get_public_key(iss)
            payload = jwt.decode(token, public_key, algorithms=["RS256"])
            _validate_issuer_actor_binding(payload)
            jti = _validate_jti(payload)
            # Decoded — propagate ALL claims to request.state
            # Canonical name is user_id; sub is set as an alias for backward compat
            sub_value = payload.get("sub", "unknown")
            request.state.user_id = sub_value
            request.state.sub = sub_value  # alias — DO NOT use in new code
            request.state.profile_id = payload.get("profile_id", sub_value)
            request.state.workspace_id = payload.get("workspace_id")
            request.state.display_name = payload.get("display_name")
            request.state.role = payload.get("role", "user")
            request.state.actor_type = payload.get("actor_type", "user")
            request.state.scopes = payload.get("scopes", [])
            request.state.iss = payload.get("iss", "user")
            request.state.max_rating = payload.get("max_rating", "all_ages")
            request.state.child_age = payload.get("child_age")
            request.state.jwt_token = token
            request.state.jwt_exp = payload.get("exp")
            request.state.jwt_jti = jti
        except jwt.ExpiredSignatureError:
            return JSONResponse(status_code=401, content={"error": "Token expired"})
        except jwt.InvalidTokenError as e:
            logger.warning(f"JWT validation failed: {e}")
            return JSONResponse(status_code=401, content={"error": "Invalid token"})
        except ValueError as e:
            logger.warning(f"JWT validation failed: {e}")
            return JSONResponse(status_code=401, content={"error": "Invalid token"})

        return await call_next(request)
