from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from brain.db.rls import platform_admin_connection
from brain.middleware.jwt_auth import require_auth
from brain.middleware.scopes import check_scopes
from brain.services.web_agent_settings import (
    HomeLocationUpdate,
    WebAgentSettingsResponse,
    fetch_web_agent_settings,
    save_home_location,
)
from jarvis_common.logging_config import get_logger

logger = get_logger("alpha_brain")

router = APIRouter(prefix="/v1/settings", tags=["settings"])


def _profile_id(request: Request) -> str:
    return str(getattr(request.state, "profile_id", None) or request.state.user_id)


@router.get("/web-agent", response_model=WebAgentSettingsResponse)
async def get_web_agent_settings(
    request: Request,
    _user_id: str = Depends(require_auth),
) -> WebAgentSettingsResponse:
    check_scopes(request, "admin")

    async with platform_admin_connection(
        source="http",
        audit_actor=f"settings_web_agent_read:{_profile_id(request)}",
    ) as conn:
        return await fetch_web_agent_settings(conn)


@router.put("/web-agent/home-location", response_model=WebAgentSettingsResponse)
async def put_web_agent_home_location(
    location: HomeLocationUpdate,
    request: Request,
    _user_id: str = Depends(require_auth),
) -> WebAgentSettingsResponse:
    check_scopes(request, "admin")
    profile_id = _profile_id(request)

    async with platform_admin_connection(
        source="http",
        audit_actor=f"settings_web_agent_home_location:{profile_id}",
    ) as conn:
        response = await save_home_location(
            conn,
            location,
            updated_by_profile_id=profile_id,
        )

    logger.info("WEB_AGENT_HOME_LOCATION_UPDATED profile=%s", profile_id)
    return response
