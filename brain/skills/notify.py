"""Notification skills."""

from __future__ import annotations

import asyncio
import json
import subprocess
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from brain.config.node_addresses import GATEWAY_URL
from brain.config.secrets import get_secret
from brain.skills.runner import SkillCall
from jarvis_common.logging_config import get_logger

logger = get_logger("alpha_brain")

GATEWAY_NOTIFY_TIMEOUT_SEC = 15

NotificationSeverity = Literal[
    "debug", "info", "needs_input", "warning", "error", "critical"
]


class PushoverSkillPayload(BaseModel):
    title: str = Field(min_length=1, max_length=250)
    message: str = Field(min_length=1, max_length=1024)
    priority: int = Field(default=0, ge=-2, le=2)
    retry: int | None = Field(default=None, ge=30, le=3600)
    expire: int | None = Field(default=None, ge=60, le=10800)
    sound: str | None = Field(default=None, min_length=1, max_length=50)
    url: str | None = Field(default=None, min_length=1, max_length=512)
    url_title: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_emergency_fields(self) -> "PushoverSkillPayload":
        if self.priority == 2:
            if self.retry is None:
                self.retry = 60
            if self.expire is None:
                self.expire = 3600
        elif self.retry is not None or self.expire is not None:
            raise ValueError("retry/expire are only valid for priority=2")
        return self


class MattermostSkillPayload(BaseModel):
    title: str = Field(min_length=1, max_length=250)
    message: str = Field(min_length=1, max_length=4000)
    severity: NotificationSeverity = "info"
    source: Literal["alpha", "forge", "watchdog"] = "alpha"
    channel_key: str = Field(
        default="alpha_events",
        min_length=1,
        max_length=32,
        pattern=r"^[a-z][a-z0-9_]{0,31}$",
    )
    root_id: str | None = Field(default=None, min_length=1, max_length=64)


class NotifySkillPayload(MattermostSkillPayload):
    fallback_to_pushover: bool = True


class NotifySkillError(RuntimeError):
    """Raised when Brain cannot deliver a provider-neutral notification."""


class PushoverSkillError(NotifySkillError):
    """Raised when Brain cannot deliver a Pushover request through Gateway."""


class MattermostSkillError(NotifySkillError):
    """Raised when Brain cannot deliver a Mattermost request through Gateway."""


def _gateway_notify_url(provider: str) -> str:
    return f"{GATEWAY_URL.rstrip('/')}/v1/notify/{provider}"


def _gateway_token() -> str:
    return get_secret("GATEWAY_TOKEN")


def _post_gateway_notify_sync(
    payload: dict[str, Any],
    *,
    provider: str,
    idempotency_key: str,
    timeout_sec: int = GATEWAY_NOTIFY_TIMEOUT_SEC,
) -> tuple[int, str]:
    args = [
        "curl",
        "-sk",
        "-m",
        str(timeout_sec),
        "-X",
        "POST",
        "-H",
        "Content-Type: application/json",
        "-H",
        f"Authorization: Bearer {_gateway_token()}",
        "-H",
        f"X-JARVIS-Idempotency-Key: {idempotency_key}",
        "-d",
        json.dumps(payload),
        _gateway_notify_url(provider),
    ]
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout_sec + 5,
            check=False,
        )
        return result.returncode, result.stdout
    except subprocess.TimeoutExpired:
        return 124, '{"detail":"timeout"}'
    except Exception as exc:
        return 1, json.dumps({"detail": str(exc)})


def _idempotency_key(call: SkillCall) -> str:
    idempotency_key = call.invocation.idempotency_key
    if not idempotency_key:
        raise NotifySkillError("idempotency_key_required")
    return idempotency_key


async def _send_gateway_provider(
    *,
    provider: str,
    payload: dict[str, Any],
    idempotency_key: str,
    error_cls: type[NotifySkillError],
    log_name: str,
) -> dict[str, Any]:
    rc, body = await asyncio.to_thread(
        _post_gateway_notify_sync,
        payload,
        provider=provider,
        idempotency_key=idempotency_key,
    )
    if rc != 0:
        logger.error("%s gateway_curl_failed rc=%s", log_name, rc)
        raise error_cls("gateway_transport_failed")

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        logger.error("%s gateway_non_json", log_name)
        raise error_cls("gateway_non_json_response") from exc

    if parsed.get("status") != "sent":
        detail = parsed.get("detail") or "gateway_rejected_notification"
        logger.error("%s gateway_rejected detail=%s", log_name, detail)
        raise error_cls(str(detail))

    return parsed


async def _send_pushover_payload(
    payload: dict[str, Any],
    *,
    idempotency_key: str,
) -> dict[str, Any]:
    parsed = await _send_gateway_provider(
        provider="pushover",
        payload=payload,
        idempotency_key=idempotency_key,
        error_cls=PushoverSkillError,
        log_name="notify.send_pushover",
    )
    logger.info("notify.send_pushover sent request_id=%s", parsed.get("request_id"))
    return {
        "status": "sent",
        "provider": "pushover",
        "request_id": parsed.get("request_id"),
        "receipt": parsed.get("receipt"),
    }


async def _send_mattermost_payload(
    payload: dict[str, Any],
    *,
    idempotency_key: str,
) -> dict[str, Any]:
    parsed = await _send_gateway_provider(
        provider="mattermost",
        payload=payload,
        idempotency_key=idempotency_key,
        error_cls=MattermostSkillError,
        log_name="notify.send_mattermost",
    )
    logger.info("notify.send_mattermost sent post_id=%s", parsed.get("post_id"))
    return {
        "status": "sent",
        "provider": "mattermost",
        "mode": parsed.get("mode"),
        "channel_key": parsed.get("channel_key"),
        "post_id": parsed.get("post_id"),
        "channel_id": parsed.get("channel_id"),
    }


async def send_pushover(call: SkillCall) -> dict[str, Any]:
    """Send a Pushover notification through Gateway.

    Pushover is now the fallback/wake-up channel. The normal Alpha ops surface
    should use ``notify.send`` or ``notify.send_mattermost``.
    """

    idempotency_key = call.invocation.idempotency_key
    if not idempotency_key:
        raise PushoverSkillError("idempotency_key_required")

    payload = PushoverSkillPayload.model_validate(dict(call.payload)).model_dump(
        exclude_none=True
    )
    return await _send_pushover_payload(payload, idempotency_key=idempotency_key)


async def send_mattermost(call: SkillCall) -> dict[str, Any]:
    """Send a Mattermost ChatOps notification through Gateway."""

    idempotency_key = call.invocation.idempotency_key
    if not idempotency_key:
        raise MattermostSkillError("idempotency_key_required")

    payload = MattermostSkillPayload.model_validate(dict(call.payload)).model_dump(
        exclude_none=True
    )
    return await _send_mattermost_payload(payload, idempotency_key=idempotency_key)


async def send_notify(call: SkillCall) -> dict[str, Any]:
    """Provider-neutral notification skill.

    Mattermost is the primary ops cockpit. Pushover is preserved as fallback so
    critical agent alerts still have a path when ChatOps is unavailable.
    """

    idempotency_key = _idempotency_key(call)
    payload = NotifySkillPayload.model_validate(dict(call.payload))
    mattermost_payload = MattermostSkillPayload.model_validate(
        payload.model_dump(exclude={"fallback_to_pushover"})
    ).model_dump(exclude_none=True)

    try:
        result = await _send_mattermost_payload(
            mattermost_payload,
            idempotency_key=idempotency_key,
        )
        result["fallback_used"] = False
        return result
    except MattermostSkillError as exc:
        if not payload.fallback_to_pushover:
            raise NotifySkillError(f"mattermost_failed:{exc}") from exc

        fallback_payload = _mattermost_to_pushover_payload(payload)
        try:
            result = await _send_pushover_payload(
                fallback_payload,
                idempotency_key=idempotency_key,
            )
        except PushoverSkillError as fallback_exc:
            raise NotifySkillError(
                f"mattermost_failed_and_pushover_failed:{fallback_exc}"
            ) from fallback_exc
        result["fallback_used"] = True
        result["primary_provider"] = "mattermost"
        return result


def _mattermost_to_pushover_payload(payload: NotifySkillPayload) -> dict[str, Any]:
    return PushoverSkillPayload(
        title=_truncate(payload.title, 250),
        message=_truncate(payload.message, 1024),
        priority=_pushover_priority_for(payload.severity),
    ).model_dump(exclude_none=True)


def _pushover_priority_for(severity: NotificationSeverity) -> int:
    return {
        "debug": -2,
        "info": -1,
        "needs_input": 0,
        "warning": 0,
        "error": 1,
        "critical": 1,
    }[severity]


def _truncate(value: str, max_length: int) -> str:
    if len(value) <= max_length:
        return value
    return value[: max_length - 3] + "..."


def notify_skill_handlers() -> dict[str, Any]:
    return {
        "notify.send": send_notify,
        "notify.send_mattermost": send_mattermost,
        "notify.send_pushover": send_pushover,
    }
