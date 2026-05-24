from __future__ import annotations

import os
from uuid import UUID

import asyncpg

from jarvis_common.logging_config import get_logger

logger = get_logger("alpha_brain")

DEFAULT_FAMILY_ID = UUID("40488626-b467-47f8-9386-72ac79b978a7")
PROFILE_TO_FAMILY_MEMBER = {
    "ken": "Ken",
    "sweta": "Sweta Gurnani",
    "ryleigh": "Ryleigh",
    "sloane": "Sloane",
}


class FamilyPinSyncError(RuntimeError):
    pass


def has_family_pin_target(profile_id: str) -> bool:
    return profile_id in PROFILE_TO_FAMILY_MEMBER


async def sync_family_pin_hash(profile_id: str, pin_hash: str) -> None:
    family_member_name = PROFILE_TO_FAMILY_MEMBER.get(profile_id)
    if not family_member_name:
        return

    family_dsn = os.environ.get("JARVIS_FAMILY_DB_DSN")
    if not family_dsn:
        raise FamilyPinSyncError("JARVIS_FAMILY_DB_DSN is not configured")

    family_id = os.environ.get("JARVIS_FAMILY_ID", str(DEFAULT_FAMILY_ID))
    try:
        family_uuid = UUID(family_id)
    except ValueError as exc:
        raise FamilyPinSyncError("JARVIS_FAMILY_ID is not a valid UUID") from exc

    try:
        conn = await asyncpg.connect(family_dsn)
        try:
            member = await conn.fetchrow(
                """
                UPDATE jarvis_family.family_members
                SET pin_hash = $1,
                    failed_attempts = 0,
                    locked_until = NULL,
                    updated_at = now()
                WHERE family_id = $2
                  AND lower(name) = lower($3)
                  AND status = 'active'
                RETURNING id
                """,
                pin_hash,
                family_uuid,
                family_member_name,
            )
        finally:
            await conn.close()
    except FamilyPinSyncError:
        raise
    except Exception as exc:
        raise FamilyPinSyncError("Family member PIN update failed") from exc

    if not member:
        raise FamilyPinSyncError(
            f"Family member mapping not found for profile {profile_id}"
        )

    logger.info(
        "FAMILY_PIN_SYNC profile=%s family_member_id=%s",
        profile_id,
        member["id"],
    )
