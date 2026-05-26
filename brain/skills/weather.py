"""Read-only weather skills."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field, model_validator

from brain.services import weather_client
from brain.skills.runner import SkillCall


class WeatherCurrentPayload(BaseModel):
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    location_label: str = Field(default="home", min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_coordinates(self) -> "WeatherCurrentPayload":
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be provided together")
        return self


WeatherClient = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


async def current(call: SkillCall) -> dict[str, Any]:
    payload = WeatherCurrentPayload.model_validate(_public_payload(call))
    client = call.payload.get("_client") or weather_client.get_current_weather
    return await client(payload.model_dump(exclude_none=True))


def weather_skill_handlers(client: WeatherClient | None = None) -> dict[str, Any]:
    if client is None:
        return {"weather.current": current}

    async def _current(call: SkillCall) -> dict[str, Any]:
        payload = WeatherCurrentPayload.model_validate(_public_payload(call))
        return await client(payload.model_dump(exclude_none=True))

    return {"weather.current": _current}


def _public_payload(call: SkillCall) -> dict[str, Any]:
    return {
        key: value for key, value in call.payload.items() if not key.startswith("_")
    }
