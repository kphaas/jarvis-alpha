from __future__ import annotations

from datetime import UTC, datetime

from brain.services import herald_linkedin_health as health


NOW = datetime(2026, 6, 27, tzinfo=UTC)


def test_required_scopes_defaults_to_publish_scope() -> None:
    assert health.required_scopes("") == ("w_member_social",)
    assert health.required_scopes("openid profile,w_member_social") == (
        "openid",
        "profile",
        "w_member_social",
    )


def test_introspection_ok_with_comma_scopes_and_ttl() -> None:
    result = health.evaluate_introspection(
        {"active": True, "scope": "openid,profile,w_member_social", "expires_in": 20},
        now=NOW,
        warn_within_seconds=10,
    )

    assert result.status == "ok"
    assert result.seconds_remaining == 20
    assert result.scopes == ["openid", "profile", "w_member_social"]


def test_introspection_missing_publish_scope_fails() -> None:
    result = health.evaluate_introspection(
        {"active": True, "scope": "openid profile", "expires_in": 20},
        now=NOW,
    )

    assert result.status == "failed"
    assert result.error_type == "LinkedInTokenMissingScope"
    assert result.missing_scopes == ["w_member_social"]


def test_introspection_expiring_soon_warns() -> None:
    result = health.evaluate_introspection(
        {"active": True, "scope": "w_member_social", "expires_in": 9},
        now=NOW,
        warn_within_seconds=10,
    )

    assert result.status == "warning"
    assert result.requires_attention
    assert result.error_type == "LinkedInTokenExpiringSoon"


def test_check_posts_token_through_gateway_proxy() -> None:
    seen = {}

    def fake_gateway(path: str, payload: dict[str, str], timeout_s: int):
        seen["path"] = path
        seen["payload"] = payload
        seen["timeout_s"] = timeout_s
        return {
            "active": True,
            "scope": "w_member_social",
            "expires_in": 2_000_000,
        }

    result = health.check_linkedin_token_health(
        access_token="access-token",
        client_id="client-id",
        client_secret="client-secret",
        now=NOW,
        post_gateway=fake_gateway,
        timeout_s=7,
    )

    assert result.status == "ok"
    assert seen == {
        "path": health.INTROSPECTION_PROXY_PATH,
        "payload": {
            "client_id": "client-id",
            "client_secret": "client-secret",
            "token": "access-token",
        },
        "timeout_s": 7,
    }
