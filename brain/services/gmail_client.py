from __future__ import annotations

import base64
import hashlib
import html
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from brain.config.secrets import get_secret

GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1"
GMAIL_TOKEN_URL = "https://oauth2.googleapis.com/token"
DEFAULT_GMAIL_USER = "me"


class GmailConfigError(RuntimeError):
    pass


class GmailClientError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_type: str | None = None,
        error_subtype: str | None = None,
        error_description: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_type = error_type
        self.error_subtype = error_subtype
        self.error_description = error_description


@dataclass(frozen=True)
class GmailMessage:
    gmail_message_id: str
    thread_id: str | None
    history_id: str | None
    sender: str | None
    subject: str | None
    received_at: datetime | None
    snippet: str | None
    body_text: str

    @property
    def body_sha256(self) -> str:
        return hashlib.sha256(self.body_text.encode("utf-8")).hexdigest()


def _secret(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value:
        return value.strip()
    try:
        return get_secret(name).strip()
    except Exception:
        return default


def _required_secret(name: str) -> str:
    value = _secret(name)
    if not value:
        raise GmailConfigError(f"{name} is not configured")
    return value


def _headers(payload: dict[str, Any]) -> dict[str, str]:
    headers = payload.get("payload", {}).get("headers", []) or []
    return {
        str(header.get("name", "")).lower(): str(header.get("value", ""))
        for header in headers
        if isinstance(header, dict)
    }


def _decode_part(data: str | None) -> str:
    if not data:
        return ""
    padded = data + ("=" * (-len(data) % 4))
    try:
        return base64.urlsafe_b64decode(padded.encode("ascii")).decode(
            "utf-8", errors="replace"
        )
    except Exception:
        return ""


def _plain_from_html(value: str) -> str:
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    value = re.sub(r"(?s)<br\s*/?>", "\n", value)
    value = re.sub(r"(?s)</p\s*>", "\n", value)
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"[ \t]+", " ", value)


def _walk_parts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    stack = [payload]
    while stack:
        part = stack.pop()
        parts.append(part)
        stack.extend(part.get("parts", []) or [])
    return parts


def _body_text(payload: dict[str, Any]) -> str:
    root = payload.get("payload", {})
    plain: list[str] = []
    html_parts: list[str] = []
    for part in _walk_parts(root):
        mime = part.get("mimeType")
        body = _decode_part(part.get("body", {}).get("data"))
        if not body:
            continue
        if mime == "text/plain":
            plain.append(body)
        elif mime == "text/html":
            html_parts.append(_plain_from_html(body))
    text = "\n".join(plain or html_parts)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def parse_gmail_message(payload: dict[str, Any]) -> GmailMessage:
    headers = _headers(payload)
    received_at = None
    if headers.get("date"):
        try:
            received_at = parsedate_to_datetime(headers["date"])
            if received_at.tzinfo is None:
                received_at = received_at.replace(tzinfo=timezone.utc)
            received_at = received_at.astimezone(timezone.utc)
        except Exception:
            received_at = None

    return GmailMessage(
        gmail_message_id=str(payload["id"]),
        thread_id=payload.get("threadId"),
        history_id=payload.get("historyId"),
        sender=headers.get("from"),
        subject=headers.get("subject"),
        received_at=received_at,
        snippet=payload.get("snippet"),
        body_text=_body_text(payload),
    )


class GmailClient:
    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        refresh_token: str | None = None,
        user_id: str | None = None,
    ) -> None:
        self.client_id = client_id or _required_secret("ALPHA_GMAIL_CLIENT_ID")
        self.client_secret = client_secret or _required_secret(
            "ALPHA_GMAIL_CLIENT_SECRET"
        )
        self.refresh_token = refresh_token or _required_secret(
            "ALPHA_GMAIL_REFRESH_TOKEN"
        )
        self.user_id = user_id or _secret("ALPHA_GMAIL_USER_ID", DEFAULT_GMAIL_USER)

    async def refresh_access_token_payload(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                GMAIL_TOKEN_URL,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": self.refresh_token,
                    "grant_type": "refresh_token",
                },
            )
        if response.status_code >= 400:
            error_payload: dict[str, Any] = {}
            try:
                error_payload = response.json()
            except Exception:
                error_payload = {}
            raise GmailClientError(
                f"Gmail OAuth refresh failed: {response.status_code}",
                status_code=response.status_code,
                error_type=error_payload.get("error"),
                error_subtype=error_payload.get("error_subtype"),
                error_description=error_payload.get("error_description"),
            )
        return response.json()

    async def _access_token(self) -> str:
        payload = await self.refresh_access_token_payload()
        token = payload.get("access_token")
        if not token:
            raise GmailClientError("Gmail OAuth response missing access_token")
        return str(token)

    async def list_message_ids(self, query: str, max_results: int = 25) -> list[str]:
        token = await self._access_token()
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{GMAIL_API_BASE}/users/{self.user_id}/messages",
                headers={"Authorization": f"Bearer {token}"},
                params={"q": query, "maxResults": max_results},
            )
        if response.status_code >= 400:
            raise GmailClientError(f"Gmail message list failed: {response.status_code}")
        return [str(msg["id"]) for msg in response.json().get("messages", [])]

    async def get_message(self, message_id: str) -> GmailMessage:
        token = await self._access_token()
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{GMAIL_API_BASE}/users/{self.user_id}/messages/{message_id}",
                headers={"Authorization": f"Bearer {token}"},
                params={"format": "full"},
            )
        if response.status_code >= 400:
            raise GmailClientError(f"Gmail message get failed: {response.status_code}")
        return parse_gmail_message(response.json())
