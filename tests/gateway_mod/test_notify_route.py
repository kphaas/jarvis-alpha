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
        seen["base_url"] = config.base_url
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
    assert response.post_id == "post-1"
    assert response.channel_id == "alerts-channel-id"
    assert seen["base_url"] == "https://mattermost.test"
    assert seen["token"] == "m" * 26
    assert seen["payload"]["channel_id"] == "alerts-channel-id"
    assert "**Alpha**" in seen["payload"]["message"]
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
