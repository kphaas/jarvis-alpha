"""Alpha-owned settings for Beacon/Web Agent behavior."""

from __future__ import annotations

from datetime import datetime
import json
from typing import Any, Literal

import asyncpg
from pydantic import BaseModel, ConfigDict, Field, field_validator

from brain.db.rls import platform_admin_connection

WEB_AGENT_SETTINGS_ID = 1


class HomeLocationUpdate(BaseModel):
    """Admin-editable home location used for free weather routing."""

    model_config = ConfigDict(str_strip_whitespace=True)

    label: str = Field(default="Home", min_length=1, max_length=80)
    postal_code: str | None = Field(default=None, max_length=20)
    city: str | None = Field(default=None, max_length=80)
    region: str | None = Field(default=None, max_length=80)
    country: str = Field(default="US", min_length=2, max_length=2)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)

    @field_validator("postal_code", "city", "region", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("country")
    @classmethod
    def _uppercase_country(cls, value: str) -> str:
        return value.upper()


class HomeLocationSetting(HomeLocationUpdate):
    updated_at: datetime | None = None
    updated_by_profile_id: str | None = None
    data_classification: Literal["personal_information"] = "personal_information"


class WebAgentSettingsResponse(BaseModel):
    home_location: HomeLocationSetting | None = None
    storage_classification: Literal["alpha_db_personal_settings"] = (
        "alpha_db_personal_settings"
    )


def _decode_jsonb(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, str):
        decoded = json.loads(value)
        return decoded if isinstance(decoded, dict) else {}
    if isinstance(value, dict):
        return value
    return {}


def _settings_row_to_response(row: asyncpg.Record | None) -> WebAgentSettingsResponse:
    if row is None:
        return WebAgentSettingsResponse()

    home_location = _decode_jsonb(row["home_location"])
    if not home_location:
        return WebAgentSettingsResponse()

    location = HomeLocationSetting(
        **HomeLocationUpdate.model_validate(home_location).model_dump(),
        updated_at=row["updated_at"],
        updated_by_profile_id=row["updated_by_profile_id"],
    )
    return WebAgentSettingsResponse(home_location=location)


async def fetch_web_agent_settings(
    conn: asyncpg.Connection,
) -> WebAgentSettingsResponse:
    row = await conn.fetchrow(
        """
        SELECT home_location, updated_at, updated_by_profile_id
        FROM public.alpha_web_agent_settings
        WHERE id = $1
        """,
        WEB_AGENT_SETTINGS_ID,
    )
    return _settings_row_to_response(row)


async def save_home_location(
    conn: asyncpg.Connection,
    location: HomeLocationUpdate,
    *,
    updated_by_profile_id: str,
) -> WebAgentSettingsResponse:
    payload = json.dumps(
        location.model_dump(mode="json", exclude_none=True),
        separators=(",", ":"),
    )
    row = await conn.fetchrow(
        """
        INSERT INTO public.alpha_web_agent_settings
            (id, home_location, updated_by_profile_id, updated_at)
        VALUES ($1, $2::jsonb, $3, now())
        ON CONFLICT (id) DO UPDATE
        SET home_location = EXCLUDED.home_location,
            updated_by_profile_id = EXCLUDED.updated_by_profile_id,
            updated_at = now()
        RETURNING home_location, updated_at, updated_by_profile_id
        """,
        WEB_AGENT_SETTINGS_ID,
        payload,
        updated_by_profile_id,
    )
    return _settings_row_to_response(row)


async def get_home_weather_coordinates() -> tuple[float, float] | None:
    """Return Alpha's configured home coordinates for weather calls, if set."""

    async with platform_admin_connection(
        source="executor",
        audit_actor="web_agent_home_weather_coordinates",
    ) as conn:
        settings = await fetch_web_agent_settings(conn)

    if settings.home_location is None:
        return None
    return settings.home_location.latitude, settings.home_location.longitude
