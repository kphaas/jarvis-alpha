"""Integration tests for the /health/ready route (AUDIT-3).

The route is exercised through a minimal FastAPI app mounting only
brain.routes.health.router, so genuine HTTP 200/503 status codes are asserted
without app lifespan / DB coupling. The 3 probes are monkeypatched at the
health-route namespace to controlled ProbeResults.

pytest-asyncio asyncio_mode=auto; TestClient calls are synchronous.
"""

from __future__ import annotations

import os

os.environ.setdefault("ALPHA_DB_DSN", "postgresql://localhost/db")
os.environ.setdefault("ALPHA_DB_DSN_WRITER", "postgresql://localhost/db")
os.environ.setdefault("ALPHA_DB_DSN_BUDDY", "postgresql://localhost/db")
os.environ.setdefault("ALPHA_GATEWAY_URL", "https://localhost:8283")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import brain.routes.health as health
from brain.health_probes import ProbeResult
from brain.middleware.jwt_auth import SKIP_PATHS


def _patch_probes(monkeypatch, *, db=True, ollama=True, temporal=True, db_msg=None):
    async def _db():
        return ProbeResult(ok=db, latency_ms=3, last_error_msg=db_msg)

    async def _ollama():
        return ProbeResult(
            ok=ollama, latency_ms=5, last_error_msg=None if ollama else "ollama down"
        )

    async def _temporal():
        return ProbeResult(
            ok=temporal,
            latency_ms=40,
            last_error_msg=None if temporal else "temporal down",
        )

    monkeypatch.setattr(health, "probe_db_pool", _db)
    monkeypatch.setattr(health, "probe_ollama", _ollama)
    monkeypatch.setattr(health, "probe_temporal", _temporal)


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(health.router)
    return TestClient(app)


def test_all_healthy_returns_200(client, monkeypatch):
    _patch_probes(monkeypatch)
    resp = client.get("/health/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["checks"]["db"]["ok"] is True
    assert body["checks"]["ollama"]["ok"] is True
    assert body["checks"]["temporal"]["ok"] is True


def test_db_fail_returns_503(client, monkeypatch):
    _patch_probes(monkeypatch, db=False, db_msg="DB pool not initialised")
    resp = client.get("/health/ready")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["checks"]["db"]["ok"] is False
    assert body["checks"]["ollama"]["ok"] is True


def test_ollama_fail_returns_503(client, monkeypatch):
    _patch_probes(monkeypatch, ollama=False)
    resp = client.get("/health/ready")
    assert resp.status_code == 503
    assert resp.json()["checks"]["ollama"]["ok"] is False


def test_temporal_fail_returns_503(client, monkeypatch):
    _patch_probes(monkeypatch, temporal=False)
    resp = client.get("/health/ready")
    assert resp.status_code == 503
    assert resp.json()["checks"]["temporal"]["ok"] is False


def test_db_timeout_returns_503(client, monkeypatch):
    _patch_probes(monkeypatch, db=False, db_msg="timeout after 200ms")
    resp = client.get("/health/ready")
    assert resp.status_code == 503
    assert resp.json()["checks"]["db"]["last_error_msg"] == "timeout after 200ms"


def test_response_shape_matches_contract(client, monkeypatch):
    _patch_probes(monkeypatch)
    body = client.get("/health/ready").json()
    assert set(body.keys()) == {"status", "checks", "ts"}
    assert set(body["checks"].keys()) == {"db", "ollama", "temporal"}
    for check in body["checks"].values():
        assert set(check.keys()) == {"ok", "latency_ms", "last_error_msg"}
    # ts is ISO-8601-ish
    assert "T" in body["ts"]


def test_health_ready_in_skip_paths():
    # Proves the new route is exempt from JWT auth (no 401).
    assert "/health/ready" in SKIP_PATHS


def test_existing_health_untouched(client, monkeypatch):
    # Backward-compat: shallow /health must keep its exact contract.
    _patch_probes(monkeypatch, db=False, ollama=False, temporal=False)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "node": "brain", "service": "jarvis-alpha"}
