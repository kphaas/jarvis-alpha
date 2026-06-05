from __future__ import annotations

import pytest

from brain.routes import costs, dev
from brain.services.gmail_client import GmailClient


@pytest.mark.asyncio
async def test_dev_github_issues_route_uses_gateway_proxy(monkeypatch):
    calls: list[tuple[str, dict]] = []

    async def fake_gateway(path: str, payload: dict, *, timeout_s: int):
        calls.append((path, payload))
        return {
            "items": [
                {"number": 1, "title": "open bug"},
                {"number": 2, "pull_request": {"url": "https://example.invalid/pr"}},
            ]
        }

    monkeypatch.setattr(dev, "call_gateway_proxy", fake_gateway)

    issues = await dev._github_open_issues("kphaas", "jarvis-alpha")

    assert issues == [{"number": 1, "title": "open bug"}]
    assert calls == [
        (
            "github/issues",
            {
                "owner": "kphaas",
                "repo": "jarvis-alpha",
                "state": "open",
                "labels": "bug",
                "per_page": 100,
            },
        )
    ]


@pytest.mark.asyncio
async def test_gmail_client_uses_gateway_proxy_for_oauth_list_and_message(monkeypatch):
    calls: list[tuple[str, dict]] = []

    async def fake_gateway(path: str, payload: dict, *, timeout_s: int):
        calls.append((path, payload))
        if path == "google_oauth/refresh":
            return {"status_code": 200, "payload": {"access_token": "access-token"}}
        if path == "gmail/list":
            return {"status_code": 200, "payload": {"messages": [{"id": "msg-1"}]}}
        if path == "gmail/message":
            return {
                "status_code": 200,
                "payload": {
                    "id": "msg-1",
                    "payload": {"headers": [], "parts": []},
                },
            }
        raise AssertionError(path)

    monkeypatch.setattr("brain.services.gmail_client.call_gateway_proxy", fake_gateway)
    client = GmailClient(
        client_id="client-id",
        client_secret="client-secret",
        refresh_token="refresh-token",
        user_id="me",
    )

    assert await client.list_message_ids("from:school") == ["msg-1"]
    message = await client.get_message("msg-1")

    assert message.gmail_message_id == "msg-1"
    assert [path for path, _payload in calls] == [
        "google_oauth/refresh",
        "gmail/list",
        "google_oauth/refresh",
        "gmail/message",
    ]


def test_anthropic_costs_use_gateway_admin_proxy(monkeypatch):
    calls: list[tuple[str, dict]] = []

    def fake_gateway(path: str, payload: dict, *, timeout_s: int):
        calls.append((path, payload))
        if payload["path"].endswith("usage_report/messages"):
            return {
                "payload": {
                    "data": [{"results": [{"key_name": "jarvis_core", "amount": 120}]}]
                }
            }
        return {
            "payload": {
                "data": [{"results": [{"key_name": "jarvis_forge", "amount": 80}]}]
            }
        }

    monkeypatch.setattr(costs, "call_gateway_proxy_sync", fake_gateway)

    result = costs._get_anthropic_mtd_sync()

    assert result["total_usd"] == 0.8
    assert [path for path, _payload in calls] == [
        "anthropic_admin",
        "anthropic_admin",
    ]
    assert {payload["path"] for _path, payload in calls} == {
        "/v1/organizations/usage_report/messages",
        "/v1/organizations/cost_report",
    }


def test_gemini_costs_use_gateway_google_billing_proxy(monkeypatch):
    calls: list[tuple[str, dict]] = []

    def fake_gateway(path: str, payload: dict, *, timeout_s: int):
        calls.append((path, payload))
        return {"payload": {"totalCost": 12.34}}

    monkeypatch.setattr(costs, "call_gateway_proxy_sync", fake_gateway)

    result = costs._get_gemini_mtd_sync()

    assert result == {"total_usd": 12.34, "source": "gcp_api"}
    assert calls == [("google_billing", {"currency_code": "USD"})]
