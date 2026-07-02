"""Unit tests for shared Gateway egress transport resilience."""

import httpx
import pytest
from fastapi import HTTPException

from gateway.resilience import transport


@pytest.fixture(autouse=True)
def reset_transport(monkeypatch, tmp_path):
    monkeypatch.setenv("GATEWAY_EGRESS_RETRY_BASE_MS", "1")
    monkeypatch.setenv("GATEWAY_EGRESS_RETRY_MAX_MS", "1")
    monkeypatch.setenv("GATEWAY_EGRESS_RETRY_JITTER_FRACTION", "0")
    monkeypatch.setenv("GATEWAY_EGRESS_DLQ_PATH", str(tmp_path / "gateway_egress.db"))
    monkeypatch.setenv("GATEWAY_EGRESS_DLQ_MAX_SIZE", "10")
    monkeypatch.delenv("GATEWAY_EGRESS_RETRY_ATTEMPTS", raising=False)
    monkeypatch.delenv("GATEWAY_EGRESS_CIRCUIT_FAILURE_THRESHOLD", raising=False)
    monkeypatch.delenv("GATEWAY_EGRESS_CIRCUIT_WINDOW_SECONDS", raising=False)
    monkeypatch.delenv("GATEWAY_EGRESS_CIRCUIT_OPEN_SECONDS", raising=False)
    transport.reset_resilience_state()
    yield
    transport.reset_resilience_state()


def _response(method: str, url: str, status_code: int, payload: dict[str, object]):
    return httpx.Response(
        status_code,
        request=httpx.Request(method, url),
        json=payload,
    )


@pytest.mark.asyncio
async def test_request_with_resilience_retries_request_error_then_succeeds():
    attempts = 0

    class FakeClient:
        def __init__(self, *, timeout: float):
            assert timeout == 5.0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url: str):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise httpx.ConnectError("boom", request=httpx.Request("GET", url))
            return _response("GET", url, 200, {"ok": True})

    response = await transport.request_with_resilience(
        operation="test-request-retry",
        method="GET",
        url="https://example.com/health",
        timeout=5.0,
        client_factory=FakeClient,
        failure_detail="Example health",
    )

    assert attempts == 2
    assert response.status_code == 200
    assert response.json() == {"ok": True}


@pytest.mark.asyncio
async def test_request_with_resilience_returns_last_retryable_response_and_records_dlq(
    monkeypatch,
):
    monkeypatch.setenv("GATEWAY_EGRESS_RETRY_ATTEMPTS", "2")
    attempts = 0

    class FakeClient:
        def __init__(self, *, timeout: float):
            assert timeout == 5.0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url: str, *, json: dict[str, object]):
            nonlocal attempts
            attempts += 1
            return _response("POST", url, 503, {"status": "retry-later", **json})

    response = await transport.request_with_resilience(
        operation="test-retryable-status",
        method="POST",
        url="https://example.com/jobs",
        timeout=5.0,
        json_body={"job": "sync"},
        client_factory=FakeClient,
        failure_detail="Example jobs",
        payload_summary={"job": "sync"},
    )

    items = await transport._dlq_for("test-retryable-status").drain(10)

    assert attempts == 2
    assert response.status_code == 503
    assert len(items) == 1
    assert items[0].reason == "http_503"
    assert items[0].payload["attempts"] == 2
    assert items[0].payload["payload_summary"] == {"job": "sync"}


@pytest.mark.asyncio
async def test_request_with_resilience_returns_503_when_circuit_is_open(monkeypatch):
    monkeypatch.setenv("GATEWAY_EGRESS_RETRY_ATTEMPTS", "1")
    monkeypatch.setenv("GATEWAY_EGRESS_CIRCUIT_FAILURE_THRESHOLD", "1")
    monkeypatch.setenv("GATEWAY_EGRESS_CIRCUIT_OPEN_SECONDS", "60")
    calls = 0

    class FakeClient:
        def __init__(self, *, timeout: float):
            assert timeout == 5.0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url: str):
            nonlocal calls
            calls += 1
            return _response("GET", url, 503, {"status": "down"})

    first = await transport.request_with_resilience(
        operation="test-circuit-open",
        method="GET",
        url="https://example.com/down",
        timeout=5.0,
        client_factory=FakeClient,
        failure_detail="Example down",
    )

    with pytest.raises(HTTPException) as exc:
        await transport.request_with_resilience(
            operation="test-circuit-open",
            method="GET",
            url="https://example.com/down",
            timeout=5.0,
            client_factory=FakeClient,
            failure_detail="Example down",
        )

    assert first.status_code == 503
    assert exc.value.status_code == 503
    assert exc.value.detail == "Example down circuit is open"
    assert calls == 1
