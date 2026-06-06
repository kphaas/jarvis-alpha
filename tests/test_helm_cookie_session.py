from __future__ import annotations

from types import SimpleNamespace

from fastapi import Response

from brain.middleware.approval_classes import classify_route
from brain.middleware.jwt_auth import ALPHA_SESSION_COOKIE, _request_token
from brain.routes.pin_auth import (
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
    assert classify_route("POST", "/v1/auth/session-cookie") == ["auth"]


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
