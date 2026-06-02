"""Unit tests for alert sink system."""

from unittest.mock import patch

import pytest

from gateway.resilience.alerts import (
    CompositeSink,
    FallbackSink,
    MattermostSink,
    MattermostWebhookSink,
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


def test_mattermost_rejects_invalid_config():
    with pytest.raises(ValueError):
        MattermostSink(base_url="", bot_token="m" * 26, channel_id="channel-1")
    with pytest.raises(ValueError):
        MattermostSink(
            base_url="mattermost.test", bot_token="m" * 26, channel_id="channel-1"
        )
    with pytest.raises(ValueError):
        MattermostSink(
            base_url="https://mattermost.test",
            bot_token="short",
            channel_id="channel-1",
        )
    with pytest.raises(ValueError):
        MattermostSink(
            base_url="https://mattermost.test", bot_token="m" * 26, channel_id="short"
        )


def test_mattermost_webhook_rejects_invalid_config():
    with pytest.raises(ValueError):
        MattermostWebhookSink(webhook_url="")
    with pytest.raises(ValueError):
        MattermostWebhookSink(webhook_url="mattermost.test/hooks/abc")
    with pytest.raises(ValueError):
        MattermostWebhookSink(
            webhook_url="https://mattermost.test/hooks/abc",
            channel_name="",
        )


async def test_mattermost_webhook_send_success_mocked():
    sink = MattermostWebhookSink(
        webhook_url="https://mattermost.test/hooks/abc",
        channel_name="alpha-events",
    )
    with patch.object(sink, "_post_sync", return_value=(0, "ok")):
        ok = await sink.send(Severity.INFO, "title", "message")
    assert ok is True


async def test_mattermost_webhook_routes_errors_to_alerts():
    sink = MattermostWebhookSink(
        webhook_url="https://mattermost.test/hooks/abc",
        channel_name="alpha-events",
    )
    seen = {}

    def fake_post(payload):
        seen.update(payload)
        return 0, "ok"

    with patch.object(sink, "_post_sync", fake_post):
        ok = await sink.send(Severity.ERROR, "title", "message")

    assert ok is True
    assert seen["channel"] == "alerts"
    assert seen["text"].startswith("🚨 **title**")
    assert "`ERROR` · `JARVIS Gateway`" in seen["text"]


async def test_mattermost_send_success_mocked():
    sink = MattermostSink(
        base_url="https://mattermost.test",
        bot_token="m" * 26,
        channel_id="alerts-channel-id",
    )
    seen = {}

    def fake_post(payload):
        seen.update(payload)
        return 0, '{"id":"post-1","channel_id":"alerts-channel-id"}'

    with patch.object(sink, "_post_sync", fake_post):
        ok = await sink.send(Severity.INFO, "title", "message")
    assert ok is True
    assert seen["message"].startswith("ℹ️ **title**")
    assert "`INFO` · `JARVIS Gateway`" in seen["message"]


async def test_mattermost_send_rejected_mocked():
    sink = MattermostSink(
        base_url="https://mattermost.test",
        bot_token="m" * 26,
        channel_id="alerts-channel-id",
    )
    with patch.object(sink, "_post_sync", return_value=(0, '{"message":"denied"}')):
        ok = await sink.send(Severity.INFO, "title", "message")
    assert ok is False


async def test_pushover_send_success_mocked():
    sink = PushoverSink(user_key="a" * 30, app_token="b" * 30)
    with patch.object(
        sink, "_post_sync", return_value=(0, '{"status":1,"request":"abc"}')
    ):
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

    ok = await CompositeSink([_FailSink(), NullSink()]).send(Severity.INFO, "t", "m")
    assert ok is True


async def test_composite_all_fail():
    class _FailSink(NullSink):
        async def send(self, severity, title, message, metadata=None):
            return False

    ok = await CompositeSink([_FailSink(), _FailSink()]).send(Severity.INFO, "t", "m")
    assert ok is False


async def test_fallback_sink_uses_fallback_only_after_primary_failure():
    calls = []

    class _Primary(NullSink):
        @property
        def name(self):
            return "primary"

        async def send(self, severity, title, message, metadata=None):
            calls.append("primary")
            return False

    class _Fallback(NullSink):
        @property
        def name(self):
            return "fallback"

        async def send(self, severity, title, message, metadata=None):
            calls.append("fallback")
            return True

    sink = FallbackSink(_Primary(), _Fallback())
    ok = await sink.send(Severity.INFO, "t", "m")

    assert ok is True
    assert sink.name == "fallback(primary->fallback)"
    assert calls == ["primary", "fallback"]


def test_factory_returns_null_when_unset(monkeypatch):
    monkeypatch.delenv("MATTERMOST_WEBHOOK_URL_ALPHA_EVENTS", raising=False)
    monkeypatch.delenv("MATTERMOST_WEBHOOK_URL_ALERTS", raising=False)
    monkeypatch.delenv("MATTERMOST_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("MATTERMOST_URL", raising=False)
    monkeypatch.delenv("MATTERMOST_BOT_TOKEN", raising=False)
    monkeypatch.delenv("MATTERMOST_CHANNEL_ALERTS_ID", raising=False)
    monkeypatch.delenv("MATTERMOST_DEFAULT_CHANNEL_ID", raising=False)
    monkeypatch.delenv("PUSHOVER_USER_KEY", raising=False)
    monkeypatch.delenv("PUSHOVER_APP_TOKEN", raising=False)
    sink = build_default_sink()
    assert sink.name == "null"


def test_factory_returns_mattermost_webhook_when_set(monkeypatch):
    monkeypatch.setenv(
        "MATTERMOST_WEBHOOK_URL_ALPHA_EVENTS",
        "https://mattermost.test/hooks/alpha",
    )
    monkeypatch.setenv("MATTERMOST_CHANNEL_ALERTS_NAME", "alerts")
    monkeypatch.delenv("MATTERMOST_URL", raising=False)
    monkeypatch.delenv("MATTERMOST_BOT_TOKEN", raising=False)
    monkeypatch.delenv("MATTERMOST_CHANNEL_ALERTS_ID", raising=False)
    monkeypatch.delenv("MATTERMOST_DEFAULT_CHANNEL_ID", raising=False)
    monkeypatch.delenv("PUSHOVER_USER_KEY", raising=False)
    monkeypatch.delenv("PUSHOVER_APP_TOKEN", raising=False)
    sink = build_default_sink()
    assert sink.name == "mattermost-webhook"


def test_factory_returns_mattermost_rest_when_set(monkeypatch):
    monkeypatch.delenv("MATTERMOST_WEBHOOK_URL_ALPHA_EVENTS", raising=False)
    monkeypatch.delenv("MATTERMOST_WEBHOOK_URL_ALERTS", raising=False)
    monkeypatch.delenv("MATTERMOST_WEBHOOK_URL", raising=False)
    monkeypatch.setenv("MATTERMOST_URL", "https://mattermost.test")
    monkeypatch.setenv("MATTERMOST_BOT_TOKEN", "m" * 26)
    monkeypatch.setenv("MATTERMOST_CHANNEL_ALERTS_ID", "alerts-channel-id")
    monkeypatch.delenv("PUSHOVER_USER_KEY", raising=False)
    monkeypatch.delenv("PUSHOVER_APP_TOKEN", raising=False)
    sink = build_default_sink()
    assert sink.name == "mattermost"


def test_factory_returns_pushover_when_only_pushover_set(monkeypatch):
    monkeypatch.delenv("MATTERMOST_WEBHOOK_URL_ALPHA_EVENTS", raising=False)
    monkeypatch.delenv("MATTERMOST_WEBHOOK_URL_ALERTS", raising=False)
    monkeypatch.delenv("MATTERMOST_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("MATTERMOST_URL", raising=False)
    monkeypatch.delenv("MATTERMOST_BOT_TOKEN", raising=False)
    monkeypatch.delenv("MATTERMOST_CHANNEL_ALERTS_ID", raising=False)
    monkeypatch.delenv("MATTERMOST_DEFAULT_CHANNEL_ID", raising=False)
    monkeypatch.setenv("PUSHOVER_USER_KEY", "a" * 30)
    monkeypatch.setenv("PUSHOVER_APP_TOKEN", "b" * 30)
    sink = build_default_sink()
    assert sink.name == "pushover"


def test_factory_returns_fallback_when_both_set(monkeypatch):
    monkeypatch.setenv(
        "MATTERMOST_WEBHOOK_URL_ALPHA_EVENTS",
        "https://mattermost.test/hooks/alpha",
    )
    monkeypatch.delenv("MATTERMOST_URL", raising=False)
    monkeypatch.delenv("MATTERMOST_BOT_TOKEN", raising=False)
    monkeypatch.delenv("MATTERMOST_CHANNEL_ALERTS_ID", raising=False)
    monkeypatch.delenv("MATTERMOST_DEFAULT_CHANNEL_ID", raising=False)
    monkeypatch.setenv("PUSHOVER_USER_KEY", "a" * 30)
    monkeypatch.setenv("PUSHOVER_APP_TOKEN", "b" * 30)
    sink = build_default_sink()
    assert sink.name == "fallback(mattermost-webhook->pushover)"


def test_factory_falls_back_on_invalid_length(monkeypatch):
    monkeypatch.delenv("MATTERMOST_WEBHOOK_URL_ALPHA_EVENTS", raising=False)
    monkeypatch.delenv("MATTERMOST_WEBHOOK_URL_ALERTS", raising=False)
    monkeypatch.delenv("MATTERMOST_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("MATTERMOST_URL", raising=False)
    monkeypatch.delenv("MATTERMOST_BOT_TOKEN", raising=False)
    monkeypatch.delenv("MATTERMOST_CHANNEL_ALERTS_ID", raising=False)
    monkeypatch.delenv("MATTERMOST_DEFAULT_CHANNEL_ID", raising=False)
    monkeypatch.setenv("PUSHOVER_USER_KEY", "short")
    monkeypatch.setenv("PUSHOVER_APP_TOKEN", "also_short")
    sink = build_default_sink()
    assert sink.name == "null"
