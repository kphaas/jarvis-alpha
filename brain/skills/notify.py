"""Notification skills."""

from __future__ import annotations

import asyncio
import json
import subprocess
from typing import Any

from pydantic import BaseModel, Field, model_validator

from brain.config.node_addresses import GATEWAY_URL
from brain.config.secrets import get_secret
from brain.skills.runner import SkillCall
from jarvis_common.logging_config import get_logger

logger = get_logger("alpha_brain")

GATEWAY_NOTIFY_TIMEOUT_SEC = 15


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


class PushoverSkillError(RuntimeError):
    """Raised when Brain cannot deliver a Pushover request through Gateway."""


def _gateway_notify_url() -> str:
    return f"{GATEWAY_URL.rstrip('/')}/v1/notify/pushover"


def _gateway_token() -> str:
    return get_secret("GATEWAY_TOKEN")


def _post_gateway_notify_sync(
    payload: dict[str, Any],
    *,
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
        _gateway_notify_url(),
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


async def send_pushover(call: SkillCall) -> dict[str, Any]:
    """Send a Pushover notification through Gateway.

    Defense in depth: SkillPolicyGate enforces idempotency before this handler
    runs, and the handler also refuses missing keys so direct test/helper calls
    cannot accidentally bypass the mutation contract.
    """

    idempotency_key = call.invocation.idempotency_key
    if not idempotency_key:
        raise PushoverSkillError("idempotency_key_required")

    payload = PushoverSkillPayload.model_validate(dict(call.payload)).model_dump(
        exclude_none=True
    )
    rc, body = await asyncio.to_thread(
        _post_gateway_notify_sync,
        payload,
        idempotency_key=idempotency_key,
    )
    if rc != 0:
        logger.error("notify.send_pushover gateway_curl_failed rc=%s", rc)
        raise PushoverSkillError("gateway_transport_failed")

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        logger.error("notify.send_pushover gateway_non_json")
        raise PushoverSkillError("gateway_non_json_response") from exc

    if parsed.get("status") != "sent":
        detail = parsed.get("detail") or "gateway_rejected_notification"
        logger.error("notify.send_pushover gateway_rejected detail=%s", detail)
        raise PushoverSkillError(str(detail))

    logger.info("notify.send_pushover sent request_id=%s", parsed.get("request_id"))
    return {
        "status": "sent",
        "provider": "pushover",
        "request_id": parsed.get("request_id"),
        "receipt": parsed.get("receipt"),
    }


def notify_skill_handlers() -> dict[str, Any]:
    return {"notify.send_pushover": send_pushover}
