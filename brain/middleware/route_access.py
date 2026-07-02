from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from brain.middleware.approval_classes import lookup_route_registry
from jarvis_common.logging_config import get_logger

logger = get_logger("alpha_brain")


@dataclass(frozen=True)
class RouteAccessPolicy:
    admin_only: bool = False


# ponytail: phase 1 starts admin-only on the riskiest unscoped families.
# Widen this to named scopes once non-admin operator tokens actually carry them.
ROUTE_ACCESS_POLICIES: dict[str, RouteAccessPolicy] = {
    "GET /v1/home/summary": RouteAccessPolicy(admin_only=True),
    "GET /v1/mesh/status": RouteAccessPolicy(admin_only=True),
    "GET /v1/mesh/certs": RouteAccessPolicy(admin_only=True),
    "GET /v1/logs/query": RouteAccessPolicy(admin_only=True),
    "GET /v1/unifi/status": RouteAccessPolicy(admin_only=True),
    "GET /v1/unifi/wan": RouteAccessPolicy(admin_only=True),
    "GET /v1/unifi/clients": RouteAccessPolicy(admin_only=True),
    "GET /v1/unifi/summary": RouteAccessPolicy(admin_only=True),
    "GET /v1/unifi/health-check": RouteAccessPolicy(admin_only=True),
    "GET /v1/home/homie/state": RouteAccessPolicy(admin_only=True),
    "GET /v1/home/homie/events/stream": RouteAccessPolicy(admin_only=True),
    "POST /v1/home/homie/action": RouteAccessPolicy(admin_only=True),
    "POST /v1/home/homie/intent": RouteAccessPolicy(admin_only=True),
    "POST /v1/home/homie/voice-intent": RouteAccessPolicy(admin_only=True),
    "POST /v1/home/homie/approvals/{approval_id}/review": RouteAccessPolicy(
        admin_only=True
    ),
    "POST /v1/home/homie/approvals/{approval_id}/resume": RouteAccessPolicy(
        admin_only=True
    ),
    "POST /v1/home/homie/approvals/{approval_id}/execute": RouteAccessPolicy(
        admin_only=True
    ),
    "GET /v1/costs/summary": RouteAccessPolicy(admin_only=True),
    "GET /v1/costs/budget": RouteAccessPolicy(admin_only=True),
    "GET /v1/costs/credit": RouteAccessPolicy(admin_only=True),
    "GET /v1/costs/hardware": RouteAccessPolicy(admin_only=True),
    "GET /v1/costs/outcomes": RouteAccessPolicy(admin_only=True),
    "GET /v1/costs/perplexity": RouteAccessPolicy(admin_only=True),
    "GET /v1/costs/power": RouteAccessPolicy(admin_only=True),
    "GET /v1/costs/subscriptions": RouteAccessPolicy(admin_only=True),
    "GET /v1/metrics/power/current": RouteAccessPolicy(admin_only=True),
    "GET /v1/metrics/power/history": RouteAccessPolicy(admin_only=True),
    "GET /v1/prompts": RouteAccessPolicy(admin_only=True),
    "GET /v1/prompts/": RouteAccessPolicy(admin_only=True),
    "GET /v1/prompts/{prompt_id}": RouteAccessPolicy(admin_only=True),
    "POST /v1/costs/budget/{provider}": RouteAccessPolicy(admin_only=True),
    "POST /v1/costs/credit": RouteAccessPolicy(admin_only=True),
    "POST /v1/costs/perplexity": RouteAccessPolicy(admin_only=True),
    "POST /v1/costs/power/rate": RouteAccessPolicy(admin_only=True),
    "POST /v1/costs/subscriptions": RouteAccessPolicy(admin_only=True),
    "POST /v1/prompts": RouteAccessPolicy(admin_only=True),
    "POST /v1/prompts/": RouteAccessPolicy(admin_only=True),
    "DELETE /v1/costs/subscriptions/{sub_id}": RouteAccessPolicy(admin_only=True),
}


def resolve_route_access_policy(
    method: str,
    path: str,
) -> RouteAccessPolicy | None:
    return lookup_route_registry(method, path, ROUTE_ACCESS_POLICIES)


def _is_admin_user(request: Request) -> bool:
    return (
        getattr(request.state, "actor_type", "user") == "user"
        and getattr(request.state, "role", None) == "admin"
    )


def enforce_route_access(request: Request) -> JSONResponse | None:
    policy = resolve_route_access_policy(request.method, request.url.path)
    if policy is None:
        return None

    if policy.admin_only and not _is_admin_user(request):
        logger.warning(
            "ROUTE_ACCESS_DENIED path=%s actor_type=%s role=%s",
            request.url.path,
            getattr(request.state, "actor_type", "unknown"),
            getattr(request.state, "role", "unknown"),
        )
        return JSONResponse(
            status_code=403, content={"detail": "admin_session_required"}
        )

    return None


class RouteAccessMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)

        denied = enforce_route_access(request)
        if denied is not None:
            return denied

        return await call_next(request)
