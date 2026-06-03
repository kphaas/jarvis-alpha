from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from brain.middleware.approval_classes import classify_route, determine_risk_tier
from brain.middleware import jwt_auth
from brain.routes import metrics
from brain.routes.metrics import PowerReading, require_power_writer


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


def test_bridge_prefix_uses_route_local_service_token_auth():
    assert jwt_auth.ROUTE_TOKEN_AUTH_PREFIXES == {"/v1/bridge/"}
    assert "/v1/bridge/approvals/submit" not in jwt_auth.SKIP_PATHS


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


@pytest.mark.asyncio
async def test_power_ingest_uses_platform_admin_rls_context(monkeypatch):
    seen = {}

    class FakeConn:
        async def execute(self, query, *args):
            seen["query"] = query
            seen["args"] = args
            return "INSERT 0 1"

    @asynccontextmanager
    async def fake_platform_admin_connection(*, source, audit_actor, pool=None):
        seen["source"] = source
        seen["audit_actor"] = audit_actor
        yield FakeConn()

    monkeypatch.setattr(
        metrics,
        "platform_admin_connection",
        fake_platform_admin_connection,
    )

    response = await metrics.post_power(
        PowerReading(node_name="Brain", watts=12.5, cpu_pct=4.2, source="test"),
        issuer="brain",
    )

    assert response == {"status": "ok", "node": "Brain", "watts": 12.5}
    assert seen["source"] == "http"
    assert seen["audit_actor"] == "metrics:brain"
    assert "INSERT INTO alpha_power_readings" in seen["query"]
    assert seen["args"] == ("Brain", 12.5, 4.2, "test")
