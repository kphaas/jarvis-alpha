from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Request

from brain.db.rls import RLSContext, rls_connection, rls_context_connection

DEFAULT_VAULT_WORKSPACE_ID = "personal"


def vault_workspace_id(request: Request) -> str:
    workspace_id = getattr(request.state, "workspace_id", None)
    if isinstance(workspace_id, str) and workspace_id.strip():
        normalized = workspace_id.strip()
        request.state.workspace_id = normalized
        return normalized
    request.state.workspace_id = DEFAULT_VAULT_WORKSPACE_ID
    return DEFAULT_VAULT_WORKSPACE_ID


def ensure_vault_workspace(request: Request) -> None:
    vault_workspace_id(request)


def can_read_vault(request: Request) -> bool:
    actor_type = getattr(request.state, "actor_type", "user")
    role = getattr(request.state, "role", None)
    if actor_type == "user" and role == "admin":
        return True
    scopes = set(getattr(request.state, "scopes", []) or [])
    return "*" in scopes or "vault.read" in scopes


def _can_use_vault_service_context(request: Request) -> bool:
    role = getattr(request.state, "role", None)
    if role == "admin":
        return True
    scopes = set(getattr(request.state, "scopes", []) or [])
    return bool({"*", "admin", "vault.read", "vault.write"} & scopes)


def _audit_actor(request: Request) -> str:
    return str(
        getattr(request.state, "user_sub", None)
        or getattr(request.state, "user_id", None)
        or "unknown"
    )


@asynccontextmanager
async def vault_rls_connection(request: Request):
    """Open an RLS-safe connection for Alpha vault tables.

    Service tokens are authorized by route-level scope checks. Once authorized,
    they need a platform-admin RLS role to write or read private vault rows,
    while still running as the non-bypass app DB role.
    """
    if _can_use_vault_service_context(request):
        ctx = RLSContext.platform_admin(
            source="http",
            audit_actor=_audit_actor(request),
            user_id=str(getattr(request.state, "user_id", None) or "unknown"),
            workspace_id=vault_workspace_id(request),
        )
        async with rls_context_connection(ctx, set_app_role=True) as conn:
            yield conn
        return

    async with rls_connection(request) as conn:
        yield conn
