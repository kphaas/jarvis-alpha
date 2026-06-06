from __future__ import annotations

import os
from dataclasses import dataclass
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
PROFILE_TO_FAMILY_MEMBER_ID = {
    "ken": UUID("abb3b4a8-8bfc-4a10-bdf6-c1c12993e493"),
    "ryleigh": UUID("6d9a1744-bd0f-42d7-a22c-6f3548bc1c8d"),
    "sloane": UUID("aef30dc4-bc6f-4497-9ef2-1b527d2a96a6"),
}


class FamilyPinSyncError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class FamilyPinTarget:
    member_name: str
    member_id: UUID | None


def has_family_pin_target(profile_id: str) -> bool:
    return profile_id in PROFILE_TO_FAMILY_MEMBER


def _family_member_id_for_profile(profile_id: str) -> UUID | None:
    env_name = f"JARVIS_FAMILY_MEMBER_ID_{profile_id.upper()}"
    env_value = os.environ.get(env_name)
    if env_value:
        try:
            return UUID(env_value)
        except ValueError as exc:
            raise FamilyPinSyncError(f"{env_name} is not a valid UUID") from exc
    return PROFILE_TO_FAMILY_MEMBER_ID.get(profile_id)


def _family_pin_target(profile_id: str) -> FamilyPinTarget | None:
    family_member_name = PROFILE_TO_FAMILY_MEMBER.get(profile_id)
    if not family_member_name:
        return None
    return FamilyPinTarget(
        member_name=family_member_name,
        member_id=_family_member_id_for_profile(profile_id),
    )


async def sync_family_pin_hash(profile_id: str, pin_hash: str) -> None:
    target = _family_pin_target(profile_id)
    if target is None:
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
                  AND (
                    ($3::uuid IS NOT NULL AND id = $3::uuid)
                    OR lower(name) = lower($4)
                  )
                  AND status = 'active'
                RETURNING id
                """,
                pin_hash,
                family_uuid,
                target.member_id,
                target.member_name,
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
