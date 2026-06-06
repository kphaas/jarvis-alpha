from __future__ import annotations

from types import SimpleNamespace

from fastapi import Response

from brain.middleware.approval_classes import classify_route, determine_risk_tier
from brain.middleware.jwt_auth import ALPHA_SESSION_COOKIE, _request_token
from brain.routes.pin_auth import (
    _session_broker_response,
    _session_cookie_max_age_seconds,
    _set_alpha_session_cookie,
)


def _request(*, authorization: str = "", cookie: str = ""):
    return SimpleNamespace(
        headers={"Authorization": authorization} if authorization else {},
        cookies={ALPHA_SESSION_COOKIE: cookie} if cookie else {},
    )


def test_jwt_request_token_accepts_httponly_session_cookie() -> None:
    assert _request_token(_request(cookie="cookie-token")) == "cookie-token"


def test_jwt_request_token_prefers_authorization_header() -> None:
    token = _request_token(
        _request(authorization="Bearer header-token", cookie="cookie-token")
    )

    assert token == "header-token"


def test_pin_auth_sets_secure_httponly_session_cookie() -> None:
    response = Response()

    _set_alpha_session_cookie(response, "jwt-token", max_age_seconds=3600)

    cookie = response.headers["set-cookie"]
    assert f"{ALPHA_SESSION_COOKIE}=jwt-token" in cookie
    assert "HttpOnly" in cookie
    assert "Max-Age=3600" in cookie
    assert "Path=/" in cookie
    assert "SameSite=strict" in cookie
    assert "Secure" in cookie


def test_session_cookie_refresh_route_is_classified_as_auth() -> None:
    classes = classify_route("POST", "/v1/auth/session-cookie")

    assert classes == ["auth"]
    assert determine_risk_tier(classes) == "T2"


def test_current_session_route_is_classified_as_auth() -> None:
    classes = classify_route("GET", "/v1/auth/session")

    assert classes == ["auth"]
    assert determine_risk_tier(classes) == "T2"


def test_session_cookie_max_age_uses_remaining_jwt_lifetime(monkeypatch) -> None:
    monkeypatch.setattr("brain.routes.pin_auth.time.time", lambda: 1_000)
    request = SimpleNamespace(state=SimpleNamespace(jwt_exp=4_600))

    assert _session_cookie_max_age_seconds(request) == 3_600


def test_session_cookie_max_age_never_drops_below_one(monkeypatch) -> None:
    monkeypatch.setattr("brain.routes.pin_auth.time.time", lambda: 1_000)
    request = SimpleNamespace(state=SimpleNamespace(jwt_exp=900))

    assert _session_cookie_max_age_seconds(request) == 1


def test_session_cookie_max_age_falls_back_to_session_hours(monkeypatch) -> None:
    monkeypatch.setenv("ALPHA_SESSION_HOURS", "2")
    request = SimpleNamespace(state=SimpleNamespace())

    assert _session_cookie_max_age_seconds(request) == 7_200


def test_session_broker_reports_operator_apps_authorized_without_token_leak() -> None:
    request = SimpleNamespace(
        state=SimpleNamespace(
            user_id="ken",
            profile_id="ken",
            role="admin",
            actor_type="user",
            workspace_id="workspace-1",
            max_rating="adult",
            child_age=None,
            scopes=["*"],
            jwt_token="secret-token",
            jwt_exp=1_803_985_200,
        )
    )

    payload = _session_broker_response(request).model_dump()

    assert payload["authenticated"] is True
    assert payload["session"]["expires_at"] == "2027-03-02T11:00:00Z"
    assert payload["principal"]["profile_id"] == "ken"
    assert payload["applications"] == {
        "helm": {
            "status": "authorized",
            "required_scopes": ["helm.read"],
            "granted_scopes": ["*"],
            "capabilities": [
                "alpha.summary.read",
                "family.summary.read",
                "financial.summary.read",
                "medical.safety.read",
                "helm.action.status.read",
                "helm.action.propose",
            ],
        },
        "family": {
            "status": "authorized",
            "required_scopes": ["helm.read"],
            "granted_scopes": ["*"],
            "capabilities": ["family.summary.read"],
        },
        "privacy": {
            "status": "authorized",
            "required_scopes": ["privacy.read"],
            "granted_scopes": ["*"],
            "capabilities": ["privacy.manual_workflow.read"],
        },
        "financial": {
            "status": "authorized",
            "required_scopes": ["financial.read"],
            "granted_scopes": ["*"],
            "capabilities": ["financial.summary.read"],
        },
        "medical": {
            "status": "authorized",
            "required_scopes": ["helm.read"],
            "granted_scopes": ["*"],
            "capabilities": ["medical.safety.read"],
        },
    }
    assert "secret-token" not in str(payload)


def test_session_broker_reports_missing_app_scopes_for_non_admin() -> None:
    request = SimpleNamespace(
        state=SimpleNamespace(
            user_id="ryleigh",
            profile_id="ryleigh",
            role="child",
            actor_type="user",
            max_rating="all_ages",
            scopes=["ask", "chat.read"],
        )
    )

    payload = _session_broker_response(request).model_dump()

    for application in ("helm", "privacy", "family", "financial", "medical"):
        assert payload["applications"][application]["status"] == "missing_scope"
        assert payload["applications"][application]["capabilities"] == []
