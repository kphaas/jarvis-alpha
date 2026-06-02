import pytest
from fastapi import HTTPException

from gateway.routes.notify import (
    MattermostNotifyRequest,
    PushoverNotifyRequest,
    mattermost_notify,
    pushover_notify,
)


def _secret(name: str) -> str:
    values = {
        "GATEWAY_TOKEN": "gateway-token",
        "PUSHOVER_USER_KEY": "u" * 30,
        "PUSHOVER_APP_TOKEN": "a" * 30,
        "MATTERMOST_URL": "https://mattermost.test",
        "MATTERMOST_BOT_TOKEN": "m" * 26,
        "MATTERMOST_DEFAULT_CHANNEL_ID": "alerts-channel-id",
        "MATTERMOST_CHANNEL_ALPHA_EVENTS_ID": "alpha-events-channel-id",
        "MATTERMOST_CHANNEL_ALERTS_ID": "alerts-channel-id",
        "MATTERMOST_CHANNEL_DREAM_ID": "dream-channel-id",
    }
    return values[name]


@pytest.mark.asyncio
async def test_pushover_notify_sends_form_payload(monkeypatch):
    seen = {}

    def fake_post(payload):
        seen.update(payload)
        return 0, '{"status":1,"request":"abc","receipt":"r1"}'

    monkeypatch.setattr("gateway.routes.notify.get_secret", _secret)
    monkeypatch.setattr("gateway.routes.notify._post_pushover_sync", fake_post)

    response = await pushover_notify(
        PushoverNotifyRequest(title="Alpha", message="hello", priority=1),
        authorization="Bearer gateway-token",
    )

    assert response.status == "sent"
    assert response.request_id == "abc"
    assert response.receipt == "r1"
    assert seen["token"] == "a" * 30
    assert seen["user"] == "u" * 30
    assert seen["priority"] == "1"


@pytest.mark.asyncio
async def test_pushover_notify_rejects_bad_token(monkeypatch):
    called = False

    def fake_post(payload):
        nonlocal called
        called = True

    monkeypatch.setattr("gateway.routes.notify.get_secret", _secret)
    monkeypatch.setattr("gateway.routes.notify._post_pushover_sync", fake_post)

    with pytest.raises(HTTPException) as exc:
        await pushover_notify(
            PushoverNotifyRequest(title="Alpha", message="hello"),
            authorization="Bearer wrong-token",
        )

    assert exc.value.status_code == 403
    assert called is False


@pytest.mark.asyncio
async def test_pushover_notify_defaults_emergency_fields(monkeypatch):
    seen = {}

    def fake_post(payload):
        seen.update(payload)
        return 0, '{"status":1,"request":"urgent"}'

    monkeypatch.setattr("gateway.routes.notify.get_secret", _secret)
    monkeypatch.setattr("gateway.routes.notify._post_pushover_sync", fake_post)

    await pushover_notify(
        PushoverNotifyRequest(title="Critical", message="wake up", priority=2),
        authorization="Bearer gateway-token",
    )

    assert seen["priority"] == "2"
    assert seen["retry"] == "60"
    assert seen["expire"] == "3600"


@pytest.mark.asyncio
async def test_pushover_notify_rejects_invalid_secret_lengths(monkeypatch):
    monkeypatch.setattr(
        "gateway.routes.notify.get_secret",
        lambda name: "gateway-token" if name == "GATEWAY_TOKEN" else "short",
    )

    with pytest.raises(HTTPException) as exc:
        await pushover_notify(
            PushoverNotifyRequest(title="Alpha", message="hello"),
            authorization="Bearer gateway-token",
        )

    assert exc.value.status_code == 500
    assert exc.value.detail == "Pushover secrets are invalid"


@pytest.mark.asyncio
async def test_pushover_notify_sanitizes_provider_rejection(monkeypatch):
    monkeypatch.setattr("gateway.routes.notify.get_secret", _secret)
    monkeypatch.setattr(
        "gateway.routes.notify._post_pushover_sync",
        lambda payload: (0, '{"status":0,"errors":["bad user"]}'),
    )

    with pytest.raises(HTTPException) as exc:
        await pushover_notify(
            PushoverNotifyRequest(title="Alpha", message="hello"),
            authorization="Bearer gateway-token",
        )

    assert exc.value.status_code == 502
    assert exc.value.detail == "Pushover rejected notification"


@pytest.mark.asyncio
async def test_mattermost_notify_sends_rest_payload(monkeypatch):
    seen = {}

    def fake_post(config, payload):
        seen["mode"] = config.mode
        seen["url"] = config.url
        seen["token"] = config.bot_token
        seen["payload"] = payload
        return 0, '{"id":"post-1","channel_id":"alerts-channel-id"}'

    monkeypatch.setattr("gateway.routes.notify.get_secret", _secret)
    monkeypatch.setattr("gateway.routes.notify._post_mattermost_sync", fake_post)

    response = await mattermost_notify(
        MattermostNotifyRequest(
            title="Alpha",
            message="Network Watchdog healthy",
            severity="info",
            channel_key="alerts",
        ),
        authorization="Bearer gateway-token",
    )

    assert response.status == "sent"
    assert response.mode == "rest"
    assert response.channel_key == "alerts"
    assert response.post_id == "post-1"
    assert response.channel_id == "alerts-channel-id"
    assert seen["mode"] == "rest"
    assert seen["url"] == "https://mattermost.test/api/v4/posts"
    assert seen["token"] == "m" * 26
    assert seen["payload"]["channel_id"] == "alerts-channel-id"
    assert seen["payload"]["message"].startswith("ℹ️ **Alpha**")
    assert "`INFO` · `JARVIS Alpha`" in seen["payload"]["message"]
    assert seen["payload"]["props"]["jarvis"]["severity"] == "info"


@pytest.mark.asyncio
async def test_mattermost_notify_uses_channel_key_secret(monkeypatch):
    seen = {}

    def fake_post(config, payload):
        seen["payload"] = payload
        return 0, '{"id":"post-2","channel_id":"dream-channel-id"}'

    monkeypatch.setattr("gateway.routes.notify.get_secret", _secret)
    monkeypatch.setattr("gateway.routes.notify._post_mattermost_sync", fake_post)

    await mattermost_notify(
        MattermostNotifyRequest(
            title="Dream Mode",
            message="Soak complete",
            channel_key="dream",
        ),
        authorization="Bearer gateway-token",
    )

    assert seen["payload"]["channel_id"] == "dream-channel-id"


@pytest.mark.asyncio
async def test_mattermost_notify_prefers_incoming_webhook(monkeypatch):
    seen = {}

    def secret(name: str) -> str:
        if name == "MATTERMOST_WEBHOOK_URL_ALPHA_EVENTS":
            return "https://mattermost.tail40ed36.ts.net/hooks/alpha"
        if name == "GATEWAY_TOKEN":
            return "gateway-token"
        raise KeyError(name)

    def fake_post(config, payload):
        seen["mode"] = config.mode
        seen["url"] = config.url
        seen["payload"] = payload
        return 0, "ok"

    monkeypatch.setattr("gateway.routes.notify.get_secret", secret)
    monkeypatch.setattr("gateway.routes.notify._post_mattermost_sync", fake_post)

    response = await mattermost_notify(
        MattermostNotifyRequest(title="Alpha", message="Routine event"),
        authorization="Bearer gateway-token",
    )

    assert response.status == "sent"
    assert response.mode == "webhook"
    assert response.channel_key == "alpha_events"
    assert response.post_id is None
    assert seen["mode"] == "webhook"
    assert seen["url"] == "https://mattermost.tail40ed36.ts.net/hooks/alpha"
    assert seen["payload"]["channel"] == "alpha-events"
    assert seen["payload"]["text"].startswith("ℹ️ **Alpha**")


@pytest.mark.asyncio
async def test_mattermost_notify_routes_needs_input_to_cross_cutting_channel(
    monkeypatch,
):
    seen = {}

    def secret(name: str) -> str:
        if name == "MATTERMOST_WEBHOOK_URL_ALPHA_EVENTS":
            return "https://mattermost.tail40ed36.ts.net/hooks/alpha"
        if name == "GATEWAY_TOKEN":
            return "gateway-token"
        raise KeyError(name)

    def fake_post(config, payload):
        seen["channel_key"] = config.channel_key
        seen["payload"] = payload
        return 0, "ok"

    monkeypatch.setattr("gateway.routes.notify.get_secret", secret)
    monkeypatch.setattr("gateway.routes.notify._post_mattermost_sync", fake_post)

    response = await mattermost_notify(
        MattermostNotifyRequest(
            title="Approval",
            message="Ken review needed",
            severity="needs_input",
        ),
        authorization="Bearer gateway-token",
    )

    assert response.channel_key == "needs_input"
    assert seen["channel_key"] == "needs_input"
    assert seen["payload"]["channel"] == "needs-input"


@pytest.mark.asyncio
async def test_mattermost_notify_routes_security_alerts_to_dedicated_webhook(
    monkeypatch,
):
    seen = {}

    def secret(name: str) -> str:
        if name == "MATTERMOST_WEBHOOK_URL_SECURITY_ALERTS":
            return "https://mattermost.tail40ed36.ts.net/hooks/security"
        if name == "MATTERMOST_WEBHOOK_URL_ALPHA_EVENTS":
            return "https://mattermost.tail40ed36.ts.net/hooks/alpha"
        if name == "GATEWAY_TOKEN":
            return "gateway-token"
        raise KeyError(name)

    def fake_post(config, payload):
        seen["channel_key"] = config.channel_key
        seen["url"] = config.url
        seen["payload"] = payload
        return 0, "ok"

    monkeypatch.setattr("gateway.routes.notify.get_secret", secret)
    monkeypatch.setattr("gateway.routes.notify._post_mattermost_sync", fake_post)

    response = await mattermost_notify(
        MattermostNotifyRequest(
            title="Porchlight",
            message="Security check failed",
            severity="critical",
            channel_key="security_alerts",
        ),
        authorization="Bearer gateway-token",
    )

    assert response.channel_key == "security_alerts"
    assert seen["channel_key"] == "security_alerts"
    assert seen["url"] == "https://mattermost.tail40ed36.ts.net/hooks/security"
    assert seen["payload"]["channel"] == "security-alerts"
    assert seen["payload"]["text"].startswith("🔥 **Porchlight**")
    assert "`CRITICAL` · `JARVIS Alpha`" in seen["payload"]["text"]


@pytest.mark.asyncio
async def test_mattermost_notify_rejects_bad_token(monkeypatch):
    called = False

    def fake_post(config, payload):
        nonlocal called
        called = True

    monkeypatch.setattr("gateway.routes.notify.get_secret", _secret)
    monkeypatch.setattr("gateway.routes.notify._post_mattermost_sync", fake_post)

    with pytest.raises(HTTPException) as exc:
        await mattermost_notify(
            MattermostNotifyRequest(title="Alpha", message="hello"),
            authorization="Bearer wrong-token",
        )

    assert exc.value.status_code == 403
    assert called is False


@pytest.mark.asyncio
async def test_mattermost_notify_sanitizes_provider_rejection(monkeypatch):
    monkeypatch.setattr("gateway.routes.notify.get_secret", _secret)
    monkeypatch.setattr(
        "gateway.routes.notify._post_mattermost_sync",
        lambda config, payload: (0, '{"message":"No permission"}'),
    )

    with pytest.raises(HTTPException) as exc:
        await mattermost_notify(
            MattermostNotifyRequest(title="Alpha", message="hello"),
            authorization="Bearer gateway-token",
        )

    assert exc.value.status_code == 502
    assert exc.value.detail == "Mattermost rejected notification"
