from __future__ import annotations

from contextlib import asynccontextmanager
import os
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException, Response
import pytest

os.environ.setdefault("ALPHA_DB_DSN", "postgresql://localhost/db")
os.environ.setdefault("ALPHA_DB_DSN_WRITER", "postgresql://localhost/db")
os.environ.setdefault("ALPHA_DB_DSN_BUDDY", "postgresql://localhost/db")
os.environ.setdefault("ALPHA_GATEWAY_URL", "https://localhost:8283")

from brain.middleware import jwt_auth
from brain.routes import buddy, pin_auth


def test_jwt_auth_rejects_missing_issuer_even_with_user_key(tmp_path, monkeypatch):
    user_key = tmp_path / "jwt_public.pem"
    user_key.write_text("user-public-key", encoding="utf-8")
    monkeypatch.setattr(jwt_auth, "_KEY_REGISTRY", {"user": user_key})

    with pytest.raises(ValueError, match="Missing issuer claim"):
        jwt_auth._get_public_key(None)


def test_jwt_auth_rejects_service_presenting_user_actor_type() -> None:
    with pytest.raises(ValueError, match="issuer_actor_type_mismatch"):
        jwt_auth._validate_issuer_actor_binding({"iss": "brain", "actor_type": "user"})


def test_jwt_auth_rejects_revoked_jti(monkeypatch) -> None:
    monkeypatch.setenv(jwt_auth.ALPHA_REVOKED_JTIS_ENV, "revoked-jti")

    with pytest.raises(ValueError, match="revoked_jti"):
        jwt_auth._validate_jti({"jti": "revoked-jti"})


@pytest.mark.asyncio
async def test_pin_auth_locks_profile_after_repeated_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_auth._PIN_ATTEMPTS.clear()
    now = [1_000.0]
    private_key = tmp_path / "jwt_private.pem"
    private_key.write_text("private-key", encoding="utf-8")

    class FakeConn:
        async def fetchrow(self, query, *args):
            if "FROM alpha_profiles" in query:
                return {
                    "id": "ken",
                    "role": "admin",
                    "display_name": "Ken",
                    "max_rating": "adult",
                    "child_age": None,
                    "pin_hash": "PLACEHOLDER_MIGRATE_FROM_ALPHA_PIN",
                }
            if "FROM alpha_workspace_users" in query:
                return None
            raise AssertionError(f"unexpected query: {query}")

    @asynccontextmanager
    async def fake_platform_admin_connection(*, source, audit_actor, pool=None):
        assert source == "http"
        assert audit_actor == "auth_pin"
        yield FakeConn()

    monkeypatch.setattr(
        pin_auth,
        "platform_admin_connection",
        fake_platform_admin_connection,
    )
    monkeypatch.setattr(pin_auth, "get_secret", lambda name: "2468")
    monkeypatch.setattr(pin_auth.time, "time", lambda: now[0])
    monkeypatch.setattr(pin_auth.jwt, "encode", lambda *args, **kwargs: "jwt-token")
    monkeypatch.setenv("ALPHA_JWT_PRIVATE_KEY", str(private_key))

    for _ in range(4):
        with pytest.raises(HTTPException) as exc:
            await pin_auth.authenticate_pin(
                pin_auth.PinRequest(pin="0000", profile_id="ken"),
                Response(),
            )
        assert exc.value.status_code == 401

    with pytest.raises(HTTPException) as exc:
        await pin_auth.authenticate_pin(
            pin_auth.PinRequest(pin="0000", profile_id="ken"),
            Response(),
        )
    assert exc.value.status_code == 429
    assert exc.value.detail == "pin_temporarily_locked"
    assert exc.value.headers == {"Retry-After": "300"}

    with pytest.raises(HTTPException) as exc:
        await pin_auth.authenticate_pin(
            pin_auth.PinRequest(pin="2468", profile_id="ken"),
            Response(),
        )
    assert exc.value.status_code == 429

    now[0] += 301
    response = Response()
    payload = await pin_auth.authenticate_pin(
        pin_auth.PinRequest(pin="2468", profile_id="ken"),
        response,
    )

    assert payload == {"token": "jwt-token", "expires_at": "1970-01-02T00:21:41Z"}
    assert "alpha_session=jwt-token" in response.headers["set-cookie"]
    assert pin_auth._PIN_ATTEMPTS == {}


def _buddy_request(*, user_id: str) -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace(user_id=user_id))


def test_buddy_route_rejects_caller_selected_user_id() -> None:
    request = _buddy_request(user_id="ken")

    with pytest.raises(HTTPException) as exc:
        buddy._principal_buddy_user_id(request, "ryleigh")

    assert exc.value.status_code == 403
    assert exc.value.detail == "buddy_user_mismatch"


@pytest.mark.asyncio
async def test_buddy_mark_read_uses_authenticated_principal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}
    event_id = "00000000-0000-0000-0000-000000000123"

    class FakeConn:
        async def fetchval(self, query, *args):
            calls["query"] = query
            calls["args"] = args
            return args[0]

    @asynccontextmanager
    async def fake_rls_connection(request):
        yield FakeConn()

    monkeypatch.setattr(buddy, "rls_connection", fake_rls_connection)

    result = await buddy.mark_read(event_id, _buddy_request(user_id="ken"))

    assert result == {"marked_read": event_id}
    assert "user_id = $2 OR user_id IS NULL" in str(calls["query"])
    assert calls["args"] == (event_id, "ken")
