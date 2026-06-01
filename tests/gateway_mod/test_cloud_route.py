import pytest
from fastapi import HTTPException

from gateway.routes import cloud_routes


def test_cloud_route_rejects_missing_bearer(monkeypatch):
    monkeypatch.setattr(cloud_routes, "get_secret", lambda name: "gateway-token")

    with pytest.raises(HTTPException) as exc:
        cloud_routes._authorize_gateway_call("gateway-token")

    assert exc.value.status_code == 403


def test_cloud_route_rejects_bad_token(monkeypatch):
    monkeypatch.setattr(cloud_routes, "get_secret", lambda name: "gateway-token")

    with pytest.raises(HTTPException) as exc:
        cloud_routes._authorize_gateway_call("Bearer wrong-token")

    assert exc.value.status_code == 403


def test_cloud_route_accepts_gateway_token(monkeypatch):
    monkeypatch.setattr(cloud_routes, "get_secret", lambda name: "gateway-token")

    cloud_routes._authorize_gateway_call("Bearer gateway-token")
