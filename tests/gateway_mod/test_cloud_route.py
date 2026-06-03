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


@pytest.mark.asyncio
async def test_github_issues_uses_fixed_github_endpoint(monkeypatch):
    monkeypatch.setattr(cloud_routes, "get_secret", lambda name: "gateway-token")
    seen: dict[str, object] = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return [{"number": 123, "title": "tighten proxy"}]

    class FakeClient:
        def __init__(self, *, timeout: float):
            seen["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, *, params, headers):
            seen["url"] = url
            seen["params"] = params
            seen["headers"] = headers
            return FakeResponse()

    monkeypatch.setattr(cloud_routes.httpx, "AsyncClient", FakeClient)

    result = await cloud_routes.github_issues(
        cloud_routes.GithubIssuesRequest(
            owner="kphaas",
            repo="jarvis-alpha",
            labels="security",
        ),
        authorization="Bearer gateway-token",
    )

    assert seen["url"] == "https://api.github.com/repos/kphaas/jarvis-alpha/issues"
    assert seen["params"] == {"state": "open", "per_page": 100, "labels": "security"}
    assert seen["headers"]["Authorization"] == "Bearer gateway-token"
    assert result == {"items": [{"number": 123, "title": "tighten proxy"}]}


@pytest.mark.asyncio
async def test_anthropic_admin_rejects_unsupported_path(monkeypatch):
    monkeypatch.setattr(cloud_routes, "get_secret", lambda name: "gateway-token")

    with pytest.raises(HTTPException) as exc:
        await cloud_routes.anthropic_admin(
            cloud_routes.AnthropicAdminRequest(
                path="/v1/messages",
                params={},
            ),
            authorization="Bearer gateway-token",
        )

    assert exc.value.status_code == 400
