"""Unit tests for alert sink system — Null, Pushover (mocked), Composite, factory."""

from unittest.mock import patch

import pytest

from gateway.resilience.alerts import (
    CompositeSink,
    NullSink,
    PUSHOVER_PRIORITY,
    PushoverSink,
    Severity,
    build_default_sink,
)


async def test_null_sink_always_succeeds():
    sink = NullSink()
    assert sink.name == "null"
    ok = await sink.send(Severity.INFO, "t", "m")
    assert ok is True


async def test_null_sink_all_severities():
    sink = NullSink()
    for sev in Severity:
        assert await sink.send(sev, "t", "m") is True


def test_pushover_rejects_empty_keys():
    with pytest.raises(ValueError):
        PushoverSink(user_key="", app_token="a" * 30)
    with pytest.raises(ValueError):
        PushoverSink(user_key="a" * 30, app_token="")


def test_pushover_rejects_wrong_length():
    with pytest.raises(ValueError):
        PushoverSink(user_key="a" * 29, app_token="b" * 30)
    with pytest.raises(ValueError):
        PushoverSink(user_key="a" * 30, app_token="b" * 31)


def test_pushover_priority_mapping():
    assert PUSHOVER_PRIORITY[Severity.DEBUG] == -2
    assert PUSHOVER_PRIORITY[Severity.INFO] == -1
    assert PUSHOVER_PRIORITY[Severity.WARNING] == 0
    assert PUSHOVER_PRIORITY[Severity.ERROR] == 1
    assert PUSHOVER_PRIORITY[Severity.CRITICAL] == 2


async def test_pushover_send_success_mocked():
    sink = PushoverSink(user_key="a" * 30, app_token="b" * 30)
    with patch.object(sink, "_post_sync", return_value=(0, '{"status":1,"request":"abc"}')):
        ok = await sink.send(Severity.INFO, "title", "message")
    assert ok is True


async def test_pushover_send_rejected_mocked():
    sink = PushoverSink(user_key="a" * 30, app_token="b" * 30)
    with patch.object(
        sink, "_post_sync", return_value=(0, '{"status":0,"errors":["bad user"]}')
    ):
        ok = await sink.send(Severity.INFO, "title", "message")
    assert ok is False


async def test_pushover_send_curl_failure_mocked():
    sink = PushoverSink(user_key="a" * 30, app_token="b" * 30)
    with patch.object(sink, "_post_sync", return_value=(1, "")):
        ok = await sink.send(Severity.INFO, "title", "message")
    assert ok is False


async def test_pushover_never_raises_on_exception():
    sink = PushoverSink(user_key="a" * 30, app_token="b" * 30)
    with patch.object(sink, "_post_sync", side_effect=Exception("boom")):
        ok = await sink.send(Severity.INFO, "title", "message")
    assert ok is False


async def test_composite_fan_out_any_success():
    s1 = NullSink()
    s2 = NullSink()
    sink = CompositeSink([s1, s2])
    ok = await sink.send(Severity.INFO, "t", "m")
    assert ok is True
    assert "composite" in sink.name


async def test_composite_requires_at_least_one():
    with pytest.raises(ValueError):
        CompositeSink([])


async def test_composite_any_success_wins():
    class _FailSink(NullSink):
        async def send(self, severity, title, message, metadata=None):
            return False

    ok = await CompositeSink([_FailSink(), NullSink()]).send(
        Severity.INFO, "t", "m"
    )
    assert ok is True


async def test_composite_all_fail():
    class _FailSink(NullSink):
        async def send(self, severity, title, message, metadata=None):
            return False

    ok = await CompositeSink([_FailSink(), _FailSink()]).send(
        Severity.INFO, "t", "m"
    )
    assert ok is False


def test_factory_returns_null_when_unset(monkeypatch):
    monkeypatch.delenv("PUSHOVER_USER_KEY", raising=False)
    monkeypatch.delenv("PUSHOVER_APP_TOKEN", raising=False)
    sink = build_default_sink()
    assert sink.name == "null"


def test_factory_returns_pushover_when_set(monkeypatch):
    monkeypatch.setenv("PUSHOVER_USER_KEY", "a" * 30)
    monkeypatch.setenv("PUSHOVER_APP_TOKEN", "b" * 30)
    sink = build_default_sink()
    assert sink.name == "pushover"


def test_factory_falls_back_on_invalid_length(monkeypatch):
    monkeypatch.setenv("PUSHOVER_USER_KEY", "short")
    monkeypatch.setenv("PUSHOVER_APP_TOKEN", "also_short")
    sink = build_default_sink()
    assert sink.name == "null"
