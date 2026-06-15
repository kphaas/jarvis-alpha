from __future__ import annotations

import importlib.util
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest


def _load_script_module():
    path = Path(__file__).resolve().parents[1] / "scripts/run_beacon_quality_canary.py"
    spec = importlib.util.spec_from_file_location("run_beacon_quality_canary", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_quality_canary_runner_injects_writer_password(monkeypatch) -> None:
    monkeypatch.setenv(
        "ALPHA_DB_DSN_WRITER",
        "postgresql://jarvis_alpha_writer@localhost:5432/jarvis_alpha",
    )
    monkeypatch.setenv("ALPHA_WRITER_DB_PASSWORD", "writer password")

    module = _load_script_module()

    parsed = urlsplit(module._writer_dsn())
    assert parsed.username == "jarvis_alpha_writer"
    assert unquote(parsed.password or "") == "writer password"
    assert parsed.hostname == "127.0.0.1"
    assert parsed.port == 5432
    assert parsed.path == "/jarvis_alpha"


def test_quality_canary_runner_preserves_non_loopback_dsn(monkeypatch) -> None:
    monkeypatch.setenv(
        "ALPHA_DB_DSN_WRITER",
        "postgresql://jarvis_alpha_writer@db.internal:5432/jarvis_alpha?sslmode=require",
    )
    monkeypatch.setenv("ALPHA_WRITER_DB_PASSWORD", "writer password")

    module = _load_script_module()

    parsed = urlsplit(module._writer_dsn())
    assert parsed.hostname == "db.internal"
    assert parsed.query == "sslmode=require"


@pytest.mark.asyncio
async def test_quality_canary_runner_uses_one_shot_pool(monkeypatch) -> None:
    module = _load_script_module()
    calls: dict[str, object] = {}

    class FakePool:
        pass

    async def fake_create_pool(dsn: str, *, min_size: int, max_size: int) -> FakePool:
        calls["dsn"] = dsn
        calls["min_size"] = min_size
        calls["max_size"] = max_size
        return FakePool()

    monkeypatch.setattr(module.asyncpg, "create_pool", fake_create_pool)

    pool = await module._create_canary_pool("postgresql://user@127.0.0.1/db")

    assert isinstance(pool, FakePool)
    assert calls == {
        "dsn": "postgresql://user@127.0.0.1/db",
        "min_size": 1,
        "max_size": 1,
    }
