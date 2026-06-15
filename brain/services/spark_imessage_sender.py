"""Send-capable Spark iMessage adapter.

This module is separate from the read-only BlueBubbles client so draft/context
reads stay fail-closed against send endpoints.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Any

import httpx

from brain.config.secrets import get_secret
from brain.services.bluebubbles_client import (
    BLUEBUBBLES_TIMEOUT_SEC,
    DEFAULT_BLUEBUBBLES_BASE_URL,
    BlueBubblesClientError,
    BlueBubblesConfigError,
    BlueBubblesPolicyError,
)

SPARK_IMESSAGE_SEND_ENABLED = "SPARK_IMESSAGE_SEND_ENABLED"


@dataclass(frozen=True, slots=True)
class SparkIMessageSendResult:
    status: int
    message: str
    message_ref_hash: str | None


class SparkIMessageSendClient:
    """BlueBubbles text sender guarded by an explicit runtime enable flag."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        password: str | None = None,
        send_enabled: bool | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_s: float = BLUEBUBBLES_TIMEOUT_SEC,
    ) -> None:
        self.base_url = (
            base_url or _optional_config("BLUEBUBBLES_BASE_URL") or ""
        ).rstrip("/")
        if not self.base_url:
            self.base_url = DEFAULT_BLUEBUBBLES_BASE_URL
        self.password = password or _required_config("BLUEBUBBLES_PASSWORD")
        self.send_enabled = (
            _send_enabled_from_config() if send_enabled is None else bool(send_enabled)
        )
        self._transport = transport
        self._timeout_s = timeout_s

    async def send_text_to_chat(
        self,
        *,
        chat_guid: str,
        text: str,
    ) -> SparkIMessageSendResult:
        if not self.send_enabled:
            raise BlueBubblesPolicyError("spark_imessage_send_disabled")
        clean_guid = chat_guid.strip()
        clean_text = text.strip()
        if not clean_guid:
            raise BlueBubblesConfigError("spark_imessage_chat_guid_missing")
        if not clean_text:
            raise BlueBubblesPolicyError("spark_imessage_send_text_missing")
        if len(clean_text) > 4000:
            raise BlueBubblesPolicyError("spark_imessage_send_text_too_long")

        payload = await self._request(
            "POST",
            "/api/v1/message/text",
            json_body={"chatGuid": clean_guid, "text": clean_text},
        )
        data = _dict(payload.get("data"))
        raw_ref = data.get("guid") or data.get("id") or data.get("messageGuid")
        return SparkIMessageSendResult(
            status=_int(payload.get("status")),
            message=str(payload.get("message") or ""),
            message_ref_hash=_hash_ref(raw_ref) if raw_ref else None,
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, object],
    ) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self._timeout_s,
                transport=self._transport,
            ) as client:
                response = await client.request(
                    method,
                    path,
                    params={"password": self.password},
                    json=json_body,
                )
        except httpx.RequestError as exc:
            raise BlueBubblesClientError(
                f"BlueBubbles {method} {path} failed: request_error"
            ) from exc

        if response.status_code >= 400:
            raise BlueBubblesClientError(
                f"BlueBubbles {method} {path} failed",
                status_code=response.status_code,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise BlueBubblesClientError(
                f"BlueBubbles {method} {path} returned non-json"
            ) from exc
        if not isinstance(payload, dict):
            raise BlueBubblesClientError(
                f"BlueBubbles {method} {path} returned invalid payload"
            )
        if _int(payload.get("status")) >= 400:
            raise BlueBubblesClientError(
                f"BlueBubbles {method} {path} returned API error",
                status_code=_int(payload.get("status")),
            )
        return payload


def _send_enabled_from_config() -> bool:
    value = _optional_config(SPARK_IMESSAGE_SEND_ENABLED)
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _optional_config(name: str) -> str | None:
    value = os.environ.get(name)
    if value:
        return value.strip()
    try:
        secret_value = get_secret(name)
    except Exception:
        return None
    return secret_value.strip() if secret_value and secret_value.strip() else None


def _required_config(name: str) -> str:
    value = _optional_config(name)
    if not value:
        raise BlueBubblesConfigError(f"{name} is not configured")
    return value


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _hash_ref(value: object) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()
