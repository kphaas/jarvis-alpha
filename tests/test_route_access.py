from __future__ import annotations

from starlette.requests import Request

from brain.middleware.route_access import (
    enforce_route_access,
    resolve_route_access_policy,
)


def _request(
    path: str,
    *,
    method: str = "GET",
    role: str = "admin",
    actor_type: str = "user",
) -> Request:
    request = Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "headers": [],
            "state": {},
        }
    )
    request.state.role = role
    request.state.actor_type = actor_type
    return request


def test_route_access_uses_parameterized_match_for_homie_approvals() -> None:
    policy = resolve_route_access_policy(
        "POST",
        "/v1/home/homie/approvals/abc/review",
    )

    assert policy is not None
    assert policy.admin_only is True


def test_route_access_denies_child_unifi_read() -> None:
    response = enforce_route_access(_request("/v1/unifi/status", role="child"))

    assert response is not None
    assert response.status_code == 403
    assert response.body == b'{"detail":"admin_session_required"}'


def test_route_access_denies_service_homie_action() -> None:
    response = enforce_route_access(
        _request(
            "/v1/home/homie/action",
            method="POST",
            role="admin",
            actor_type="service",
        )
    )

    assert response is not None
    assert response.status_code == 403


def test_route_access_denies_child_mesh_status() -> None:
    response = enforce_route_access(_request("/v1/mesh/status", role="child"))

    assert response is not None
    assert response.status_code == 403


def test_route_access_denies_child_logs_query() -> None:
    response = enforce_route_access(_request("/v1/logs/query", role="child"))

    assert response is not None
    assert response.status_code == 403


def test_route_access_denies_child_health_agents() -> None:
    response = enforce_route_access(_request("/v1/health/agents", role="child"))

    assert response is not None
    assert response.status_code == 403


def test_route_access_denies_child_prompt_registry_read() -> None:
    response = enforce_route_access(_request("/v1/prompts/weekly-brief", role="child"))

    assert response is not None
    assert response.status_code == 403


def test_route_access_allows_admin_costs_route() -> None:
    response = enforce_route_access(_request("/v1/costs/credit"))

    assert response is None


def test_route_access_allows_admin_prompt_registry_write() -> None:
    response = enforce_route_access(_request("/v1/prompts/", method="POST"))

    assert response is None


def test_route_access_ignores_unmanaged_routes() -> None:
    response = enforce_route_access(_request("/v1/ask", method="POST", role="child"))

    assert response is None
