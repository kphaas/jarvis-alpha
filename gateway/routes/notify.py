"""Gateway notification adapters.

Gateway is Alpha's sole internet egress. Brain sends notification requests here;
Gateway owns provider secrets and external API calls.
"""

from __future__ import annotations

import asyncio
import json
import subprocess

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field, model_validator

from jarvis_common.logging_config import get_logger
from jarvis_common.secrets import get_secret

logger = get_logger("alpha_gateway")

router = APIRouter(prefix="/v1/notify", tags=["notify"])

PUSHOVER_API_URL = "https://api.pushover.net/1/messages.json"
PUSHOVER_TIMEOUT_SEC = 10


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
