from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from brain.db.rls import platform_admin_connection
from brain.middleware.jwt_auth import require_auth
from brain.middleware.scopes import check_scopes
from brain.services.settings_identity import (
    HomeAddressIn,
    IdentitySettingsOut,
    PersonalDataSettingsOut,
    ProfileCreateIn,
    ProfileOut,
    ProfilePersonalData,
    ProfilePersonalDataIn,
    RelationshipIn,
    RelationshipOut,
    SettingsIdentityError,
    create_profile,
    delete_relationship,
    fetch_identity_settings,
    save_home_address,
    save_profile_personal_data,
    save_relationship,
)
from jarvis_common.logging_config import get_logger

logger = get_logger("alpha_brain")

router = APIRouter(prefix="/v1/settings", tags=["settings"])


def _profile_id(request: Request) -> str:
    return str(getattr(request.state, "profile_id", None) or request.state.user_id)


def _admin(request: Request) -> str:
    check_scopes(request, "admin")
    return _profile_id(request)


@router.get("/identity", response_model=IdentitySettingsOut)
async def get_identity_settings(
    request: Request,
    _user_id: str = Depends(require_auth),
) -> IdentitySettingsOut:
    profile_id = _admin(request)
    async with platform_admin_connection(
        source="http",
        audit_actor=f"settings_identity_read:{profile_id}",
    ) as conn:
        return await fetch_identity_settings(conn)


@router.post("/users", response_model=ProfileOut)
async def post_settings_user(
    body: ProfileCreateIn,
    request: Request,
    _user_id: str = Depends(require_auth),
) -> ProfileOut:
    profile_id = _admin(request)
    try:
        async with platform_admin_connection(
            source="http",
            audit_actor=f"settings_user_create:{profile_id}",
        ) as conn:
            response = await create_profile(conn, body)
    except SettingsIdentityError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    logger.info("SETTINGS_USER_CREATED profile=%s by=%s", response.id, profile_id)
    return response


@router.put(
    "/users/{target_profile_id}/personal-data", response_model=ProfilePersonalData
)
async def put_profile_personal_data(
    target_profile_id: str,
    body: ProfilePersonalDataIn,
    request: Request,
    _user_id: str = Depends(require_auth),
) -> ProfilePersonalData:
    profile_id = _admin(request)
    try:
        async with platform_admin_connection(
            source="http",
            audit_actor=f"settings_profile_personal_data:{profile_id}",
        ) as conn:
            return await save_profile_personal_data(
                conn,
                target_profile_id,
                body,
                updated_by_profile_id=profile_id,
            )
    except SettingsIdentityError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/relationships", response_model=RelationshipOut)
async def put_profile_relationship(
    body: RelationshipIn,
    request: Request,
    _user_id: str = Depends(require_auth),
) -> RelationshipOut:
    profile_id = _admin(request)
    try:
        async with platform_admin_connection(
            source="http",
            audit_actor=f"settings_relationship_save:{profile_id}",
        ) as conn:
            return await save_relationship(conn, body, updated_by_profile_id=profile_id)
    except SettingsIdentityError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/relationships/{relationship_id}")
async def delete_profile_relationship(
    relationship_id: UUID,
    request: Request,
    _user_id: str = Depends(require_auth),
) -> dict[str, str]:
    profile_id = _admin(request)
    async with platform_admin_connection(
        source="http",
        audit_actor=f"settings_relationship_delete:{profile_id}",
    ) as conn:
        deleted = await delete_relationship(conn, relationship_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="relationship not found")
    return {"status": "deleted"}


@router.put(
    "/personal-data/home-address",
    response_model=PersonalDataSettingsOut,
)
async def put_home_address(
    body: HomeAddressIn,
    request: Request,
    _user_id: str = Depends(require_auth),
) -> PersonalDataSettingsOut:
    profile_id = _admin(request)
    async with platform_admin_connection(
        source="http",
        audit_actor=f"settings_home_address:{profile_id}",
    ) as conn:
        return await save_home_address(conn, body, updated_by_profile_id=profile_id)
