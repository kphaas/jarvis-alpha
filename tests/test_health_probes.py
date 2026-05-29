"""Unit tests for brain/health_probes — the 3 readiness probes (AUDIT-3).

Each probe is exercised for happy / exception / timeout paths. Probes must
never raise: failures surface as ok=False with a short last_error_msg.
pytest-asyncio asyncio_mode=auto — no per-test decorator needed.
"""

from __future__ import annotations

import asyncio
import os

os.environ.setdefault("ALPHA_DB_DSN", "postgresql://localhost/db")
os.environ.setdefault("ALPHA_DB_DSN_WRITER", "postgresql://localhost/db")
os.environ.setdefault("ALPHA_DB_DSN_BUDDY", "postgresql://localhost/db")
os.environ.setdefault("ALPHA_GATEWAY_URL", "https://localhost:8283")

import brain.health_probes as hp
from brain.health_probes import (
    ProbeResult,
    probe_db_pool,
    probe_ollama,
    probe_temporal,
)


# ── Fakes ──────────────────────────────────────────────────────────


class _FakeAcquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *a):
        return False


class _FakeConn:
    def __init__(self, slow=False):
        self._slow = slow

    async def fetchval(self, query):
        if self._slow:
            await asyncio.sleep(1)
        return 1


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _FakeAcquire(self._conn)


class _FakeResp:
    def __init__(self, exc=None):
        self._exc = exc

    def raise_for_status(self):
        if self._exc:
            raise self._exc


class _FakeOllamaClient:
    behavior = "ok"

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url):
        if _FakeOllamaClient.behavior == "slow":
            await asyncio.sleep(1)
        if _FakeOllamaClient.behavior == "error":
            raise ConnectionError("connection refused")
        return _FakeResp()


# ── DB probe ───────────────────────────────────────────────────────


async def test_probe_db_pool_happy(monkeypatch):
    monkeypatch.setattr(hp, "get_pool", lambda: _FakePool(_FakeConn()))
    r = await probe_db_pool()
    assert isinstance(r, ProbeResult)
    assert r.ok is True
    assert r.last_error_msg is None
    assert r.latency_ms >= 0


async def test_probe_db_pool_exception(monkeypatch):
    def _boom():
        raise RuntimeError("DB pool not initialised")

    monkeypatch.setattr(hp, "get_pool", _boom)
    r = await probe_db_pool()
    assert r.ok is False
    assert "not initialised" in r.last_error_msg
    assert len(r.last_error_msg) <= 200


async def test_probe_db_pool_timeout(monkeypatch):
    monkeypatch.setattr(hp, "DB_TIMEOUT_S", 0.05)
    monkeypatch.setattr(hp, "get_pool", lambda: _FakePool(_FakeConn(slow=True)))
    r = await probe_db_pool()
    assert r.ok is False
    assert r.last_error_msg == "timeout after 50ms"


# ── Ollama probe ───────────────────────────────────────────────────


async def test_probe_ollama_happy(monkeypatch):
    _FakeOllamaClient.behavior = "ok"
    monkeypatch.setattr(hp.httpx, "AsyncClient", _FakeOllamaClient)
    r = await probe_ollama()
    assert r.ok is True
    assert r.last_error_msg is None


async def test_probe_ollama_exception(monkeypatch):
    _FakeOllamaClient.behavior = "error"
    monkeypatch.setattr(hp.httpx, "AsyncClient", _FakeOllamaClient)
    r = await probe_ollama()
    assert r.ok is False
    assert "refused" in r.last_error_msg


async def test_probe_ollama_timeout(monkeypatch):
    _FakeOllamaClient.behavior = "slow"
    monkeypatch.setattr(hp, "OLLAMA_TIMEOUT_S", 0.05)
    monkeypatch.setattr(hp.httpx, "AsyncClient", _FakeOllamaClient)
    r = await probe_ollama()
    assert r.ok is False
    assert r.last_error_msg == "timeout after 50ms"


# ── Temporal probe ─────────────────────────────────────────────────


async def test_probe_temporal_happy(monkeypatch):
    async def _connect(target, namespace=None):
        return object()

    monkeypatch.setattr(hp.Client, "connect", _connect)
    r = await probe_temporal()
    assert r.ok is True
    assert r.last_error_msg is None


async def test_probe_temporal_exception(monkeypatch):
    async def _connect(target, namespace=None):
        raise ConnectionError("temporal frontend unreachable")

    monkeypatch.setattr(hp.Client, "connect", _connect)
    r = await probe_temporal()
    assert r.ok is False
    assert "unreachable" in r.last_error_msg


async def test_probe_temporal_timeout(monkeypatch):
    async def _connect(target, namespace=None):
        await asyncio.sleep(1)
        return object()

    monkeypatch.setattr(hp, "TEMPORAL_TIMEOUT_S", 0.05)
    monkeypatch.setattr(hp.Client, "connect", _connect)
    r = await probe_temporal()
    assert r.ok is False
    assert r.last_error_msg == "timeout after 50ms"


def test_temporal_budget_is_one_second():
    # Asymmetric policy: Temporal gets 1.0s, DB + Ollama keep 200ms.
    assert hp.TEMPORAL_TIMEOUT_S == 1.0
    assert hp.DB_TIMEOUT_S == 0.2
    assert hp.OLLAMA_TIMEOUT_S == 0.2
