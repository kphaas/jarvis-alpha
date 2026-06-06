from __future__ import annotations

import pytest

from brain.routes import costs, dev
from brain.services.gmail_client import GmailClient
from brain.services.internet_scout.gateway_client import InternetScoutGatewayClient


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


@pytest.mark.asyncio
async def test_internet_scout_client_uses_gateway_search_and_fetch(monkeypatch):
    calls: list[tuple[str, dict]] = []

    async def fake_gateway(path: str, payload: dict, *, timeout_s: int):
        calls.append((path, payload))
        if path == "internet/search":
            return {
                "provider": "brave",
                "query_hash": "a" * 64,
                "fetched_at": "2026-06-06T13:00:00Z",
                "results": [
                    {
                        "title": "Beacon",
                        "url": "https://public.example.test/report",
                        "host": "public.example.test",
                        "description": "Beacon source.",
                        "risk_markers": [],
                    }
                ],
            }
        if path == "internet/fetch":
            return {
                "url": "https://public.example.test/report",
                "host": "public.example.test",
                "status_code": 200,
                "content_type": "text/html",
                "content_hash": "b" * 64,
                "fetched_at": "2026-06-06T13:00:00Z",
                "text": "Beacon source body.",
                "truncated": False,
                "risk_markers": [],
                "redirect_chain": ["https://public.example.test/report"],
            }
        raise AssertionError(path)

    monkeypatch.setattr(
        "brain.services.internet_scout.gateway_client.call_gateway_proxy",
        fake_gateway,
    )
    client = InternetScoutGatewayClient()

    search = await client.search(query="beacon")
    fetch = await client.fetch(url="https://public.example.test/report", max_bytes=1000)

    assert search.results[0].title == "Beacon"
    assert fetch.text == "Beacon source body."
    assert calls == [
        ("internet/search", {"query": "beacon", "count": 5, "provider": "brave"}),
        (
            "internet/fetch",
            {"url": "https://public.example.test/report", "max_bytes": 1000},
        ),
    ]
