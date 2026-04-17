"""Unit tests for multi-signal Dream Mode kill switch."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.dream.kill_switch import (
    ENV_VAR,
    assert_can_run,
    is_dream_mode_enabled,
    is_killed_in_db,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)


# ── Env-var tests ────────────────────────────────────────────
def test_default_disabled():
    assert is_dream_mode_enabled() is False


@pytest.mark.parametrize(
    "value", ["true", "TRUE", "True", "1", "yes", "YES", "on", "ON"]
)
def test_enabled_values(monkeypatch, value):
    monkeypatch.setenv(ENV_VAR, value)
    assert is_dream_mode_enabled() is True


@pytest.mark.parametrize(
    "value", ["false", "0", "no", "off", "", "  ", "maybe", "null"]
)
def test_disabled_values(monkeypatch, value):
    monkeypatch.setenv(ENV_VAR, value)
    assert is_dream_mode_enabled() is False


def test_whitespace_trimmed(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "  true  ")
    assert is_dream_mode_enabled() is True


def _mock_pool(flag_value_or_exc):
    pool = MagicMock()
    conn = AsyncMock()
    if isinstance(flag_value_or_exc, Exception):
        conn.fetchrow = AsyncMock(side_effect=flag_value_or_exc)
    elif flag_value_or_exc is None:
        conn.fetchrow = AsyncMock(return_value=None)
    else:
        conn.fetchrow = AsyncMock(return_value={"flag_value": flag_value_or_exc})
    conn.execute = AsyncMock()
    conn.transaction = MagicMock()
    conn.transaction.return_value.__aenter__ = AsyncMock()
    conn.transaction.return_value.__aexit__ = AsyncMock()
    pool.acquire = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock()
    return pool


# ── DB flag tests ────────────────────────────────────────────
async def test_db_flag_not_killed():
    pool = _mock_pool(False)
    assert await is_killed_in_db(pool) is False


async def test_db_flag_killed():
    pool = _mock_pool(True)
    assert await is_killed_in_db(pool) is True


async def test_db_flag_missing_row_fails_closed():
    pool = _mock_pool(None)
    assert await is_killed_in_db(pool) is True


async def test_db_flag_exception_fails_closed():
    pool = _mock_pool(RuntimeError("db unavailable"))
    assert await is_killed_in_db(pool) is True


# ── Combined assert_can_run tests ────────────────────────────
async def test_assert_raises_when_env_off():
    with pytest.raises(RuntimeError, match="env kill switch"):
        await assert_can_run(pool=None)


async def test_assert_raises_when_db_killed(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "true")
    pool = _mock_pool(True)
    with pytest.raises(RuntimeError, match="DB flag"):
        await assert_can_run(pool=pool)


async def test_assert_passes_when_all_green(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "true")
    pool = _mock_pool(False)
    await assert_can_run(pool=pool)


async def test_assert_passes_with_env_only(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "true")
    await assert_can_run(pool=None)
