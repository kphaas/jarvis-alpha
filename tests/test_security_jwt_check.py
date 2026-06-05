import json

import pytest

from brain.routes import security


@pytest.mark.asyncio
async def test_jwt_check_treats_pin_validation_error_as_public_route_pass(monkeypatch):
    calls = []

    def fake_curl_http_code(url, method="GET", max_time="5", json_body=None):
        calls.append((url, method, json_body))
        if url.endswith("/health"):
            return 200
        if url.endswith("/v1/auth/pin"):
            return 422
        return 401

    monkeypatch.setattr(security, "BRAIN_URL", "https://brain.test")
    monkeypatch.setattr(security, "_curl_http_code", fake_curl_http_code)

    result = await security.jwt_check()

    pin_check = next(
        check for check in result["checks"] if check["route"] == "POST /v1/auth/pin"
    )
    assert pin_check == {
        "route": "POST /v1/auth/pin",
        "expected": 422,
        "actual": 422,
        "pass": True,
        "type": "skip",
    }

    pin_call = next(call for call in calls if call[0].endswith("/v1/auth/pin"))
    assert pin_call[1] == "POST"
    assert json.loads(pin_call[2]) == {}
    assert result["passing"] == result["total"]
