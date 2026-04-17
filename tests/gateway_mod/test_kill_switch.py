"""Unit tests for DREAM_MODE_ENABLED kill switch."""

import os

import pytest

from gateway.dream.kill_switch import (
    ENV_VAR,
    assert_enabled,
    is_dream_mode_enabled,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)


def test_default_disabled():
    assert is_dream_mode_enabled() is False


@pytest.mark.parametrize("value", ["true", "TRUE", "True", "1", "yes", "YES", "on", "ON"])
def test_enabled_values(monkeypatch, value):
    monkeypatch.setenv(ENV_VAR, value)
    assert is_dream_mode_enabled() is True


@pytest.mark.parametrize("value", ["false", "0", "no", "off", "", "  ", "maybe", "null"])
def test_disabled_values(monkeypatch, value):
    monkeypatch.setenv(ENV_VAR, value)
    assert is_dream_mode_enabled() is False


def test_whitespace_trimmed(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "  true  ")
    assert is_dream_mode_enabled() is True


def test_assert_enabled_raises_when_off():
    with pytest.raises(RuntimeError, match="DISABLED"):
        assert_enabled()


def test_assert_enabled_passes_when_on(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "true")
    assert_enabled()
