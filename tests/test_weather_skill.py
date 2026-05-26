from decimal import Decimal

import pytest
from pydantic import ValidationError

from brain.skills.policy_gate import SkillInvocation, SkillPolicyDecision
from brain.skills.runner import SkillCall
from brain.skills.weather import WeatherCurrentPayload, current


def _call(payload: dict) -> SkillCall:
    invocation = SkillInvocation(
        agent_id="family_concierge",
        skill_name="weather.current",
    )
    decision = SkillPolicyDecision(
        outcome="allow",
        reason="policy_ok",
        agent_id="family_concierge",
        skill_name="weather.current",
        approval_tier="T1",
        skill_scope="weather.read",
        estimated_cost_usd=Decimal("0"),
    )
    return SkillCall(invocation=invocation, decision=decision, payload=payload)


@pytest.mark.asyncio
async def test_weather_current_calls_gateway_client_with_public_payload_only():
    seen: dict = {}

    async def fake_client(params: dict) -> dict:
        seen.update(params)
        return {
            "status": "ok",
            "provider": "open-meteo",
            "location_label": params["location_label"],
            "condition": "clear",
            "temperature_f": 70.0,
        }

    result = await current(
        _call(
            {
                "_client": fake_client,
                "latitude": 40.7128,
                "longitude": -74.0060,
                "location_label": "home",
            }
        )
    )

    assert result["status"] == "ok"
    assert result["condition"] == "clear"
    assert seen == {
        "latitude": 40.7128,
        "longitude": -74.006,
        "location_label": "home",
    }


def test_weather_current_requires_coordinate_pair():
    with pytest.raises(ValidationError, match="provided together"):
        WeatherCurrentPayload.model_validate({"latitude": 40.0})
