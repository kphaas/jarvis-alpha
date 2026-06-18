from __future__ import annotations

import base64
import hashlib
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import jwt
from cryptography import x509
from cryptography.hazmat.primitives import serialization

from brain.config.secrets import get_secret
from brain.services.gateway_egress import GatewayEgressError, call_gateway_proxy

DEFAULT_AT0_MAILBOXES = ("hello@at-0.com", "support@at-0.com")
GRAPH_SCOPE = "https://graph.microsoft.com/.default"


class At0MailConfigError(RuntimeError):
    pass


class At0MailGraphError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_type: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_type = error_type


@dataclass(frozen=True)
class At0MailMessage:
    graph_message_id: str
    mailbox: str
    internet_message_id: str | None
    conversation_id: str | None
    sender_name: str | None
    sender_email: str | None
    subject: str | None
    received_at: datetime | None
    body_preview: str
    web_link: str | None

    @property
    def body_preview_sha256(self) -> str:
        return hashlib.sha256(self.body_preview.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class At0MailSendResult:
    status_code: int
    provider_operation: str


def configured_mailboxes(raw: str | None = None) -> tuple[str, ...]:
    value = raw if raw is not None else _secret("AT0_HERALD_MAILBOXES")
    if not value:
        return DEFAULT_AT0_MAILBOXES
    mailboxes = tuple(item.strip().lower() for item in value.split(",") if item.strip())
    return mailboxes or DEFAULT_AT0_MAILBOXES


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
        raise At0MailConfigError(f"{name} is not configured")
    return value


def _read_secret_file(path: str) -> str:
    try:
        return Path(path).expanduser().read_text(encoding="utf-8")
    except OSError as exc:
        raise At0MailConfigError(f"{path} is not readable") from exc


def _base64url_no_padding(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _cert_thumbprint_x5t(cert_path: str) -> str:
    raw = Path(cert_path).expanduser().read_bytes()
    try:
        cert = x509.load_pem_x509_certificate(raw)
        der = cert.public_bytes(encoding=serialization.Encoding.DER)
    except ValueError:
        try:
            cert = x509.load_der_x509_certificate(raw)
            der = cert.public_bytes(encoding=serialization.Encoding.DER)
        except ValueError as exc:
            raise At0MailConfigError(f"{cert_path} is not a valid certificate") from exc
    return _base64url_no_padding(hashlib.sha1(der).digest())


def build_client_assertion(
    *,
    tenant_id: str,
    client_id: str,
    private_key_pem: str,
    certificate_x5t: str,
    now: datetime | None = None,
) -> str:
    issued_at = now or datetime.now(UTC)
    audience = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    payload = {
        "aud": audience,
        "iss": client_id,
        "sub": client_id,
        "jti": str(uuid4()),
        "nbf": int(issued_at.timestamp()),
        "exp": int((issued_at + timedelta(minutes=10)).timestamp()),
    }
    return jwt.encode(
        payload,
        private_key_pem,
        algorithm="RS256",
        headers={"x5t": certificate_x5t},
    )


def parse_graph_message(mailbox: str, payload: dict[str, Any]) -> At0MailMessage:
    sender = payload.get("from")
    email = sender.get("emailAddress") if isinstance(sender, dict) else None
    sender_name = email.get("name") if isinstance(email, dict) else None
    sender_email = email.get("address") if isinstance(email, dict) else None
    received_at = _parse_datetime(payload.get("receivedDateTime"))
    preview = _clean_preview(str(payload.get("bodyPreview") or ""))
    return At0MailMessage(
        graph_message_id=str(payload["id"]),
        mailbox=mailbox.lower(),
        internet_message_id=_optional_str(payload.get("internetMessageId")),
        conversation_id=_optional_str(payload.get("conversationId")),
        sender_name=_optional_str(sender_name),
        sender_email=_optional_str(sender_email),
        subject=_optional_str(payload.get("subject")),
        received_at=received_at,
        body_preview=preview,
        web_link=_optional_str(payload.get("webLink")),
    )


class At0MailGraphClient:
    def __init__(
        self,
        *,
        tenant_id: str | None = None,
        client_id: str | None = None,
        private_key_pem: str | None = None,
        certificate_x5t: str | None = None,
    ) -> None:
        self.tenant_id = tenant_id or _required_secret("AT0_HERALD_TENANT_ID")
        self.client_id = client_id or _required_secret("AT0_HERALD_CLIENT_ID")
        self.private_key_pem = private_key_pem or _read_secret_file(
            _required_secret("AT0_HERALD_PRIVATE_KEY_PATH")
        )
        self.certificate_x5t = certificate_x5t or _cert_thumbprint_x5t(
            _required_secret("AT0_HERALD_CERT_PATH")
        )

    async def access_token(self) -> str:
        assertion = build_client_assertion(
            tenant_id=self.tenant_id,
            client_id=self.client_id,
            private_key_pem=self.private_key_pem,
            certificate_x5t=self.certificate_x5t,
        )
        try:
            response = await call_gateway_proxy(
                "msgraph/token",
                {
                    "tenant_id": self.tenant_id,
                    "client_id": self.client_id,
                    "client_assertion": assertion,
                    "scope": GRAPH_SCOPE,
                },
                timeout_s=25,
            )
        except GatewayEgressError as exc:
            raise At0MailGraphError(f"Microsoft Graph token failed: {exc}") from exc
        return _extract_access_token(response)

    async def list_messages(
        self,
        *,
        mailbox: str,
        max_results: int = 25,
    ) -> list[At0MailMessage]:
        token = await self.access_token()
        try:
            response = await call_gateway_proxy(
                "msgraph/mailbox_messages",
                {
                    "access_token": token,
                    "mailbox": mailbox.lower(),
                    "max_results": max_results,
                },
                timeout_s=35,
            )
        except GatewayEgressError as exc:
            raise At0MailGraphError(f"Microsoft Graph mail read failed: {exc}") from exc
        status_code = int(response.get("status_code") or 502)
        payload = response.get("payload")
        if status_code >= 400:
            error_type = None
            if isinstance(payload, dict):
                error = payload.get("error")
                if isinstance(error, dict):
                    error_type = _optional_str(error.get("code"))
            raise At0MailGraphError(
                f"Microsoft Graph mail read failed: {status_code}",
                status_code=status_code,
                error_type=error_type,
            )
        if not isinstance(payload, dict):
            raise At0MailGraphError(
                "Microsoft Graph mail read returned invalid payload"
            )
        values = payload.get("value")
        if not isinstance(values, list):
            raise At0MailGraphError("Microsoft Graph mail read missing value list")
        return [
            parse_graph_message(mailbox, item)
            for item in values
            if isinstance(item, dict) and item.get("id")
        ]

    async def send_reply(
        self,
        *,
        mailbox: str,
        message_id: str,
        reply_body: str,
    ) -> At0MailSendResult:
        token = await self.access_token()
        try:
            response = await call_gateway_proxy(
                "msgraph/mailbox_reply",
                {
                    "access_token": token,
                    "mailbox": mailbox.lower(),
                    "message_id": message_id,
                    "reply_body": reply_body,
                },
                timeout_s=35,
            )
        except GatewayEgressError as exc:
            raise At0MailGraphError(f"Microsoft Graph reply failed: {exc}") from exc
        status_code = int(response.get("status_code") or 502)
        payload = response.get("payload")
        if status_code != 202:
            error_type = None
            if isinstance(payload, dict):
                error = payload.get("error")
                if isinstance(error, dict):
                    error_type = _optional_str(error.get("code"))
            raise At0MailGraphError(
                f"Microsoft Graph reply failed: {status_code}",
                status_code=status_code,
                error_type=error_type,
            )
        return At0MailSendResult(
            status_code=status_code,
            provider_operation="message.reply",
        )


async def send_at0_mail_reply(
    *,
    mailbox: str,
    message_id: str,
    reply_body: str,
) -> At0MailSendResult:
    return await At0MailGraphClient().send_reply(
        mailbox=mailbox,
        message_id=message_id,
        reply_body=reply_body,
    )


def _extract_access_token(response: dict[str, Any]) -> str:
    status_code = int(response.get("status_code") or 502)
    payload = response.get("payload")
    if status_code >= 400:
        raise At0MailGraphError(
            f"Microsoft Graph token failed: {status_code}",
            status_code=status_code,
        )
    if not isinstance(payload, dict):
        raise At0MailGraphError("Microsoft Graph token returned invalid payload")
    token = payload.get("access_token")
    if not token:
        raise At0MailGraphError("Microsoft Graph token response missing access_token")
    return str(token)


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _clean_preview(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    return value[:1000]


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
