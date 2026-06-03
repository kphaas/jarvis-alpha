from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from brain.middleware.approval_classes import classify_route, determine_risk_tier
from brain.middleware import jwt_auth
from brain.routes.metrics import require_power_writer


def _request(*, actor_type: str | None, issuer: str | None):
    return SimpleNamespace(state=SimpleNamespace(actor_type=actor_type, iss=issuer))


def test_jwt_skip_paths_are_explicit_public_surface():
    expected = (
        jwt_auth.PUBLIC_HEALTH_PATHS
        | jwt_auth.PUBLIC_AUTH_PATHS
        | jwt_auth.ROUTE_TOKEN_AUTH_PATHS
        | jwt_auth.HONEYPOT_PATHS
    )
    assert jwt_auth.SKIP_PATHS == set(expected)


@pytest.mark.parametrize(
    "path",
    [
        "/docs",
        "/openapi.json",
        "/redoc",
        "/v1/metrics/power",
        "/v1/metrics/power/current",
        "/v1/metrics/power/history",
        "/v1/metrics/power/rollup",
    ],
)
def test_sensitive_brain_paths_do_not_skip_jwt(path):
    assert path not in jwt_auth.SKIP_PATHS


def test_power_ingest_is_classified_as_t2_write():
    classes = classify_route("POST", "/v1/metrics/power")
    assert "write" in classes
    assert determine_risk_tier(classes) == "T2"


@pytest.mark.parametrize("issuer", ["brain", "gateway", "sandbox", "endpoint"])
def test_power_writer_accepts_node_service_issuers(issuer):
    assert require_power_writer(_request(actor_type="service", issuer=issuer)) == issuer


@pytest.mark.parametrize(
    ("actor_type", "issuer"),
    [
        ("user", "gateway"),
        ("agent", "buddy"),
        ("service", "forge"),
        ("service", "user"),
        (None, None),
    ],
)
def test_power_writer_rejects_non_node_service_actors(actor_type, issuer):
    with pytest.raises(HTTPException) as exc:
        require_power_writer(_request(actor_type=actor_type, issuer=issuer))
    assert exc.value.status_code == 403
    assert exc.value.detail == "power_writer_service_required"
