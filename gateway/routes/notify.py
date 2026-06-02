"""Gateway notification adapters.

Gateway is Alpha's sole internet egress. Brain sends notification requests here;
Gateway owns provider secrets and external API calls.
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
from dataclasses import dataclass
from typing import Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field, model_validator

from jarvis_common.logging_config import get_logger
from jarvis_common.secrets import get_secret

logger = get_logger("alpha_gateway")

router = APIRouter(prefix="/v1/notify", tags=["notify"])

PUSHOVER_API_URL = "https://api.pushover.net/1/messages.json"
PUSHOVER_TIMEOUT_SEC = 10
MATTERMOST_TIMEOUT_SEC = 10
MATTERMOST_CHANNEL_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


@dataclass(frozen=True, slots=True)
class MattermostConfig:
    mode: Literal["webhook", "rest"]
    url: str
    channel_key: str
    bot_token: str | None = None
    channel_id: str | None = None


MATTERMOST_DEFAULT_CHANNEL_NAMES = {
    "alpha_events": "alpha-events",
    "forge_events": "forge-events",
    "needs_input": "needs-input",
    "alerts": "alerts",
    "security_alerts": "security-alerts",
}

MATTERMOST_SOURCE_WEBHOOK_KEYS = {
    "alpha": "MATTERMOST_WEBHOOK_URL_ALPHA_EVENTS",
    "forge": "MATTERMOST_WEBHOOK_URL_FORGE_EVENTS",
    "watchdog": "MATTERMOST_WEBHOOK_URL_WATCHDOG",
}


class PushoverNotifyRequest(BaseModel):
    title: str = Field(min_length=1, max_length=250)
    message: str = Field(min_length=1, max_length=1024)
    priority: int = Field(default=0, ge=-2, le=2)
    retry: int | None = Field(default=None, ge=30, le=3600)
    expire: int | None = Field(default=None, ge=60, le=10800)
    sound: str | None = Field(default=None, min_length=1, max_length=50)
    url: str | None = Field(default=None, min_length=1, max_length=512)
    url_title: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_emergency_fields(self) -> "PushoverNotifyRequest":
        if self.priority == 2:
            if self.retry is None:
                self.retry = 60
            if self.expire is None:
                self.expire = 3600
        elif self.retry is not None or self.expire is not None:
            raise ValueError("retry/expire are only valid for priority=2")
        return self


class PushoverNotifyResponse(BaseModel):
    status: str
    provider: str = "pushover"
    request_id: str | None = None
    receipt: str | None = None


class MattermostNotifyRequest(BaseModel):
    title: str = Field(min_length=1, max_length=250)
    message: str = Field(min_length=1, max_length=4000)
    severity: Literal[
        "debug", "info", "needs_input", "warning", "error", "critical"
    ] = "info"
    source: Literal["alpha", "forge", "watchdog"] = "alpha"
    channel_key: str = Field(
        default="alpha_events",
        min_length=1,
        max_length=32,
        pattern=MATTERMOST_CHANNEL_KEY_RE.pattern,
    )
    root_id: str | None = Field(default=None, min_length=1, max_length=64)


class MattermostNotifyResponse(BaseModel):
    status: str
    provider: str = "mattermost"
    mode: Literal["webhook", "rest"]
    channel_key: str
    post_id: str | None = None
    channel_id: str | None = None


def _authorize_gateway_call(authorization: str) -> None:
    expected = get_secret("GATEWAY_TOKEN")
    if not authorization.startswith("Bearer ") or authorization[7:] != expected:
        raise HTTPException(status_code=403, detail="Invalid gateway token")


def _pushover_secrets() -> tuple[str, str]:
    user_key = get_secret("PUSHOVER_USER_KEY")
    app_token = get_secret("PUSHOVER_APP_TOKEN")
    if len(user_key) != 30 or len(app_token) != 30:
        raise HTTPException(status_code=500, detail="Pushover secrets are invalid")
    return user_key, app_token


def _post_pushover_sync(payload: dict[str, str]) -> tuple[int, str]:
    args = ["curl", "-s", "-m", str(PUSHOVER_TIMEOUT_SEC)]
    for key, value in payload.items():
        args.extend(["--form-string", f"{key}={value}"])
    args.append(PUSHOVER_API_URL)
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=PUSHOVER_TIMEOUT_SEC + 5,
            check=False,
        )
        return result.returncode, result.stdout
    except subprocess.TimeoutExpired:
        return 124, '{"status":0,"errors":["timeout"]}'
    except Exception as exc:
        return 1, json.dumps({"status": 0, "errors": [str(exc)]})


def _pushover_payload(req: PushoverNotifyRequest) -> dict[str, str]:
    user_key, app_token = _pushover_secrets()
    payload = {
        "token": app_token,
        "user": user_key,
        "title": req.title,
        "message": req.message,
        "priority": str(req.priority),
    }
    if req.priority == 2:
        payload["retry"] = str(req.retry)
        payload["expire"] = str(req.expire)
    if req.sound:
        payload["sound"] = req.sound
    if req.url:
        payload["url"] = req.url
    if req.url_title:
        payload["url_title"] = req.url_title
    return payload


def _mattermost_secret(name: str) -> str:
    try:
        value = get_secret(name).strip()
    except KeyError as exc:
        logger.error("mattermost_notify missing_config key=%s", name)
        raise HTTPException(
            status_code=500, detail="Mattermost is not configured"
        ) from exc
    if not value:
        logger.error("mattermost_notify empty_config key=%s", name)
        raise HTTPException(status_code=500, detail="Mattermost is not configured")
    return value


def _optional_mattermost_secret(name: str) -> str | None:
    try:
        value = get_secret(name).strip()
    except KeyError:
        return None
    return value or None


def _mattermost_channel_id(channel_key: str) -> str:
    if not MATTERMOST_CHANNEL_KEY_RE.fullmatch(channel_key):
        raise HTTPException(status_code=422, detail="Invalid Mattermost channel key")

    secret_name = f"MATTERMOST_CHANNEL_{channel_key.upper()}_ID"
    try:
        return get_secret(secret_name).strip()
    except KeyError:
        if channel_key == "alerts":
            return _mattermost_secret("MATTERMOST_DEFAULT_CHANNEL_ID")
        logger.error("mattermost_notify missing_channel_config key=%s", channel_key)
        raise HTTPException(
            status_code=500, detail="Mattermost channel is not configured"
        )


def _mattermost_channel_name(channel_key: str) -> str:
    secret_name = f"MATTERMOST_CHANNEL_{channel_key.upper()}_NAME"
    configured = _optional_mattermost_secret(secret_name)
    if configured:
        return configured.lstrip("#")
    return MATTERMOST_DEFAULT_CHANNEL_NAMES.get(channel_key, channel_key)


def _routed_channel_key(req: MattermostNotifyRequest) -> str:
    if req.channel_key == "security_alerts":
        return "security_alerts"
    if req.source == "watchdog":
        return "alerts"
    if req.severity in {"error", "critical"}:
        return "alerts"
    if req.severity == "needs_input":
        return "needs_input"
    return req.channel_key


def _mattermost_webhook_url(req: MattermostNotifyRequest) -> str | None:
    routed_channel = _routed_channel_key(req)
    source_key = MATTERMOST_SOURCE_WEBHOOK_KEYS[req.source]
    return (
        _optional_mattermost_secret(f"MATTERMOST_WEBHOOK_URL_{routed_channel.upper()}")
        or _optional_mattermost_secret(source_key)
        or _optional_mattermost_secret("MATTERMOST_WEBHOOK_URL")
    )


def _mattermost_config(req: MattermostNotifyRequest) -> MattermostConfig:
    routed_channel = _routed_channel_key(req)
    webhook_url = _mattermost_webhook_url(req)
    if webhook_url:
        if not webhook_url.startswith(("https://", "http://")):
            logger.error("mattermost_notify invalid_webhook_url source=%s", req.source)
            raise HTTPException(
                status_code=500, detail="Mattermost webhook URL is invalid"
            )
        return MattermostConfig(
            mode="webhook",
            url=webhook_url,
            channel_key=routed_channel,
        )

    base_url = _mattermost_secret("MATTERMOST_URL").rstrip("/")
    if not base_url.startswith(("https://", "http://")):
        logger.error("mattermost_notify invalid_base_url")
        raise HTTPException(status_code=500, detail="Mattermost URL is invalid")

    bot_token = _mattermost_secret("MATTERMOST_BOT_TOKEN")
    if len(bot_token) < 20:
        logger.error("mattermost_notify invalid_bot_token")
        raise HTTPException(status_code=500, detail="Mattermost token is invalid")

    channel_id = _mattermost_channel_id(routed_channel)
    if len(channel_id) < 8:
        logger.error("mattermost_notify invalid_channel_id key=%s", routed_channel)
        raise HTTPException(status_code=500, detail="Mattermost channel is invalid")

    return MattermostConfig(
        mode="rest",
        url=f"{base_url}/api/v4/posts",
        bot_token=bot_token,
        channel_id=channel_id,
        channel_key=routed_channel,
    )


def _mattermost_message(req: MattermostNotifyRequest) -> str:
    return "\n".join(
        [
            f"**{req.title}**",
            "",
            req.message,
            "",
            f"Severity: `{req.severity}`",
        ]
    )


def _mattermost_payload(req: MattermostNotifyRequest) -> tuple[MattermostConfig, dict]:
    config = _mattermost_config(req)
    props = {
        "jarvis": {
            "severity": req.severity,
            "source": req.source,
            "channel_key": config.channel_key,
            "requested_channel_key": req.channel_key,
        }
    }
    if config.mode == "webhook":
        payload = {
            "channel": _mattermost_channel_name(config.channel_key),
            "text": _mattermost_message(req),
            "props": props,
        }
    else:
        payload = {
            "channel_id": config.channel_id,
            "message": _mattermost_message(req),
            "props": props,
        }

    if req.root_id and config.mode == "rest":
        payload["root_id"] = req.root_id
    return config, payload


def _post_mattermost_sync(
    config: MattermostConfig,
    payload: dict,
) -> tuple[int, str]:
    args = [
        "curl",
        "-sS",
        "-m",
        str(MATTERMOST_TIMEOUT_SEC),
        "-X",
        "POST",
        "-H",
        "Content-Type: application/json",
    ]
    if config.mode == "rest":
        args.extend(["-H", f"Authorization: Bearer {config.bot_token}"])
    args.extend(
        [
            "-d",
            json.dumps(payload),
            config.url,
        ]
    )
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=MATTERMOST_TIMEOUT_SEC + 5,
            check=False,
        )
        return result.returncode, result.stdout
    except subprocess.TimeoutExpired:
        return 124, '{"message":"timeout"}'
    except Exception as exc:
        return 1, json.dumps({"message": str(exc)})


def _mattermost_success_response(
    config: MattermostConfig,
    body: str,
) -> MattermostNotifyResponse:
    if config.mode == "webhook":
        if body.strip() != "ok":
            logger.error("mattermost_notify webhook_rejected")
            raise HTTPException(
                status_code=502, detail="Mattermost rejected notification"
            )
        return MattermostNotifyResponse(
            status="sent",
            mode=config.mode,
            channel_key=config.channel_key,
        )

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        logger.error("mattermost_notify non_json_response")
        raise HTTPException(
            status_code=502, detail="Mattermost returned non-JSON"
        ) from exc

    post_id = parsed.get("id")
    channel_id = parsed.get("channel_id")
    if not post_id or not channel_id:
        logger.error("mattermost_notify rejected has_message=%s", "message" in parsed)
        raise HTTPException(status_code=502, detail="Mattermost rejected notification")

    return MattermostNotifyResponse(
        status="sent",
        mode=config.mode,
        post_id=post_id,
        channel_id=channel_id,
        channel_key=config.channel_key,
    )


@router.post("/pushover", response_model=PushoverNotifyResponse)
async def pushover_notify(
    req: PushoverNotifyRequest,
    authorization: str = Header(...),
) -> PushoverNotifyResponse:
    _authorize_gateway_call(authorization)
    rc, body = await asyncio.to_thread(_post_pushover_sync, _pushover_payload(req))
    if rc != 0:
        logger.error("pushover_notify curl_failed rc=%s", rc)
        raise HTTPException(status_code=502, detail="Pushover transport failed")

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        logger.error("pushover_notify non_json_response")
        raise HTTPException(
            status_code=502, detail="Pushover returned non-JSON"
        ) from exc

    if parsed.get("status") != 1:
        logger.error("pushover_notify rejected errors=%s", parsed.get("errors", []))
        raise HTTPException(status_code=502, detail="Pushover rejected notification")

    logger.info("pushover_notify sent request_id=%s", parsed.get("request"))
    return PushoverNotifyResponse(
        status="sent",
        request_id=parsed.get("request"),
        receipt=parsed.get("receipt"),
    )


@router.post("/mattermost", response_model=MattermostNotifyResponse)
async def mattermost_notify(
    req: MattermostNotifyRequest,
    authorization: str = Header(...),
) -> MattermostNotifyResponse:
    _authorize_gateway_call(authorization)
    config, payload = _mattermost_payload(req)
    rc, body = await asyncio.to_thread(_post_mattermost_sync, config, payload)
    if rc != 0:
        logger.error("mattermost_notify curl_failed rc=%s", rc)
        raise HTTPException(status_code=502, detail="Mattermost transport failed")

    response = _mattermost_success_response(config, body)
    logger.info(
        "mattermost_notify sent mode=%s channel_key=%s source=%s",
        response.mode,
        response.channel_key,
        req.source,
    )
    return response
