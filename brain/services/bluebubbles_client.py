"""Read-only BlueBubbles client for Spark iMessage data.

The default Spark route surface exposes only health, counts, and query
metadata. Message body reads are available only through the explicit
approved-thread method so the caller can prove a human approval and runtime
chat mapping before any content is loaded.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from brain.config.secrets import get_secret

DEFAULT_BLUEBUBBLES_BASE_URL = "http://127.0.0.1:1234"
DEFAULT_PERSONALITY_VAULT_PATH = "~/jarvis-personality"
BLUEBUBBLES_TIMEOUT_SEC = 10.0


class BlueBubblesConfigError(RuntimeError):
    """Raised when local BlueBubbles configuration is missing."""


class BlueBubblesPolicyError(RuntimeError):
    """Raised when Spark policy files do not allow the requested operation."""


class BlueBubblesClientError(RuntimeError):
    """Raised when the local BlueBubbles server cannot satisfy a read."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class SparkBlueBubblesPolicy:
    """Minimal runtime contract loaded from jarvis-personality."""

    vault_root: Path
    connector_mode: str
    drafting_mode: str
    thread_default: str
    metadata_only: bool = True
    approved_message_query_allowed: bool = False


@dataclass(frozen=True, slots=True)
class BlueBubblesHealth:
    status: str
    computer_id: str | None
    os_version: str | None
    server_version: str | None
    private_api: bool
    proxy_service: str | None
    helper_connected: bool
    detected_icloud: bool
    detected_imessage: bool


@dataclass(frozen=True, slots=True)
class BlueBubblesCounts:
    total_chats: int
    imessage_chats: int
    sms_chats: int
    rcs_chats: int
    sent_messages: int


@dataclass(frozen=True, slots=True)
class BlueBubblesRecentChatMetadata:
    status: int
    message: str
    count: int
    total: int
    offset: int
    limit: int
    data_count: int


@dataclass(frozen=True, slots=True)
class BlueBubblesMessageBody:
    message_ref_hash: str
    is_from_me: bool
    body_text: str
    created_at: str | None = None


def load_spark_bluebubbles_policy(
    vault_root: str | Path | None = None,
) -> SparkBlueBubblesPolicy:
    """Load Spark BlueBubbles policy and fail closed on missing guardrails."""

    root = _personality_vault_root(vault_root)
    connector = _read_required(root / "spark" / "connectors" / "bluebubbles.yml")
    drafting = _read_required(root / "spark" / "policies" / "message_drafting.yml")
    memory = _read_required(root / "spark" / "policies" / "memory_rules.yml")

    connector_mode = _scalar(connector, "mode")
    drafting_mode = _scalar(drafting, "current_mode")
    thread_default = _nested_scalar(connector, "thread_access", "default")

    required_blocked = (
        "POST /api/v1/message/text",
        "POST /api/v1/message/attachment",
        "POST /api/v1/message/multipart",
    )
    blocked_operations = _list_items(connector, "blocked_operations")
    allowed_operations = _list_items(connector, "allowed_operations")
    missing_blockers = [
        operation
        for operation in required_blocked
        if operation not in blocked_operations
    ]

    failures: list[str] = []
    if connector_mode != "read_only":
        failures.append("bluebubbles connector mode must be read_only")
    if drafting_mode != "draft_only":
        failures.append("Spark drafting mode must be draft_only")
    if thread_default != "denied":
        failures.append("BlueBubbles thread default must be denied")
    if missing_blockers:
        failures.append("BlueBubbles send endpoints must be blocked")
    if not _contains_scalar(connector, "log_message_bodies", "false"):
        failures.append("message body logging must be disabled")
    if not _contains_scalar(connector, "log_contact_names", "false"):
        failures.append("contact-name logging must be disabled")
    if not _contains_scalar(connector, "store_raw_threads", "false"):
        failures.append("raw thread storage must be disabled")
    if not _contains_scalar(drafting, "can_send", "false"):
        failures.append("drafting policy must block sends")
    if not _contains_scalar(memory, "durable_write", "false"):
        failures.append("draft context durable writes must be disabled")
    if not _contains_scalar(memory, "third_party_message_text", "runtime_only"):
        failures.append("third-party message text must be runtime-only")

    if failures:
        raise BlueBubblesPolicyError("; ".join(failures))

    return SparkBlueBubblesPolicy(
        vault_root=root,
        connector_mode=connector_mode,
        drafting_mode=drafting_mode,
        thread_default=thread_default,
        approved_message_query_allowed=(
            "POST /api/v1/message/query for approved chat GUIDs only"
            in allowed_operations
        ),
    )


class BlueBubblesReadOnlyClient:
    """Metadata-only BlueBubbles API adapter."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        password: str | None = None,
        policy: SparkBlueBubblesPolicy | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_s: float = BLUEBUBBLES_TIMEOUT_SEC,
    ) -> None:
        self.base_url = (base_url or _optional_config("BLUEBUBBLES_BASE_URL")).rstrip(
            "/"
        )
        if not self.base_url:
            self.base_url = DEFAULT_BLUEBUBBLES_BASE_URL
        self.password = password or _required_config("BLUEBUBBLES_PASSWORD")
        self.policy = policy or load_spark_bluebubbles_policy()
        self._transport = transport
        self._timeout_s = timeout_s

    async def health(self) -> BlueBubblesHealth:
        payload = await self._request("GET", "/api/v1/server/info")
        data = _dict(payload.get("data"))
        return BlueBubblesHealth(
            status=str(payload.get("message") or "unknown"),
            computer_id=_str_or_none(data.get("computer_id")),
            os_version=_str_or_none(data.get("os_version")),
            server_version=_str_or_none(data.get("server_version")),
            private_api=bool(data.get("private_api")),
            proxy_service=_str_or_none(data.get("proxy_service")),
            helper_connected=bool(data.get("helper_connected")),
            detected_icloud=bool(data.get("detected_icloud")),
            detected_imessage=bool(data.get("detected_imessage")),
        )

    async def counts(self) -> BlueBubblesCounts:
        chat_payload = await self._request("GET", "/api/v1/chat/count")
        sent_payload = await self._request("GET", "/api/v1/message/count/me")
        chat_data = _dict(chat_payload.get("data"))
        breakdown = _dict(chat_data.get("breakdown"))
        sent_data = _dict(sent_payload.get("data"))
        return BlueBubblesCounts(
            total_chats=_int(chat_data.get("total")),
            imessage_chats=_int(breakdown.get("iMessage")),
            sms_chats=_int(breakdown.get("SMS")),
            rcs_chats=_int(breakdown.get("RCS")),
            sent_messages=_int(sent_data.get("total")),
        )

    async def recent_chat_metadata(
        self, *, limit: int = 5, offset: int = 0
    ) -> BlueBubblesRecentChatMetadata:
        payload = await self._request(
            "POST",
            "/api/v1/chat/query",
            json_body={
                "with": ["lastmessage"],
                "sort": "lastmessage",
                "offset": offset,
                "limit": limit,
            },
        )
        metadata = _dict(payload.get("metadata"))
        data = payload.get("data")
        return BlueBubblesRecentChatMetadata(
            status=_int(payload.get("status")),
            message=str(payload.get("message") or ""),
            count=_int(metadata.get("count")),
            total=_int(metadata.get("total")),
            offset=_int(metadata.get("offset")),
            limit=_int(metadata.get("limit")),
            data_count=len(data) if isinstance(data, list) else 0,
        )

    async def approved_messages_for_chat(
        self,
        *,
        chat_guid: str,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[BlueBubblesMessageBody, ...]:
        """Read message bodies for a caller-verified, approved chat GUID."""

        if not self.policy.approved_message_query_allowed:
            raise BlueBubblesPolicyError(
                "approved BlueBubbles message query operation is not allowed"
            )
        clean_guid = chat_guid.strip()
        if not clean_guid:
            raise BlueBubblesConfigError("approved chat GUID is not configured")

        safe_limit = min(max(limit, 1), 200)
        payload = await self._request(
            "POST",
            "/api/v1/message/query",
            json_body={
                "chatGuid": clean_guid,
                "offset": max(offset, 0),
                "limit": safe_limit,
                "sort": "dateCreated",
                "with": [],
            },
        )
        data = payload.get("data")
        if not isinstance(data, list):
            return ()

        messages: list[BlueBubblesMessageBody] = []
        for index, item in enumerate(data[:safe_limit]):
            row = _dict(item)
            body_text = _message_body_text(row)
            if not body_text:
                continue
            messages.append(
                BlueBubblesMessageBody(
                    message_ref_hash=_message_ref_hash(row, index),
                    is_from_me=_message_is_from_me(row),
                    body_text=body_text,
                    created_at=_str_or_none(
                        row.get("dateCreated")
                        or row.get("date_created")
                        or row.get("created_at")
                    ),
                )
            )
        return tuple(messages)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self.policy.connector_mode != "read_only":
            raise BlueBubblesPolicyError("BlueBubbles connector is not read-only")
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


def _personality_vault_root(vault_root: str | Path | None) -> Path:
    raw = (
        str(vault_root)
        if vault_root is not None
        else os.environ.get("SPARK_PERSONALITY_VAULT")
        or os.environ.get("JARVIS_PERSONALITY_VAULT")
        or DEFAULT_PERSONALITY_VAULT_PATH
    )
    return Path(raw).expanduser()


def _optional_config(name: str) -> str | None:
    value = os.environ.get(name)
    if value:
        return value.strip()
    try:
        return get_secret(name).strip()
    except Exception:
        return None


def _required_config(name: str) -> str:
    value = _optional_config(name)
    if not value:
        raise BlueBubblesConfigError(f"{name} is not configured")
    return value


def _read_required(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise BlueBubblesPolicyError(f"missing Spark policy file: {path}") from exc


def _scalar(text: str, key: str) -> str:
    match = re.search(rf"(?m)^{re.escape(key)}:\s*([^\n#]+?)\s*$", text)
    return match.group(1).strip().strip("\"'") if match else ""


def _nested_scalar(text: str, section: str, key: str) -> str:
    section_match = re.search(
        rf"(?ms)^{re.escape(section)}:\s*\n(?P<body>(?:^[ ]+[^\n]*\n?)*)",
        text,
    )
    if not section_match:
        return ""
    match = re.search(
        rf"(?m)^\s+{re.escape(key)}:\s*([^\n#]+?)\s*$",
        section_match.group("body"),
    )
    return match.group(1).strip().strip("\"'") if match else ""


def _contains_scalar(text: str, key: str, value: str) -> bool:
    return bool(
        re.search(
            rf"(?m)^\s*{re.escape(key)}:\s*{re.escape(value)}\s*(?:#.*)?$",
            text,
        )
    )


def _list_items(text: str, key: str) -> list[str]:
    match = re.search(
        rf"(?ms)^{re.escape(key)}:\s*\n(?P<body>(?:^\s+-\s+[^\n]+\n?)*)",
        text,
    )
    if not match:
        return []
    return [
        line.split("-", 1)[1].strip().strip("\"'")
        for line in match.group("body").splitlines()
        if line.lstrip().startswith("-")
    ]


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _str_or_none(value: Any) -> str | None:
    return str(value) if value is not None else None


def _message_body_text(row: dict[str, Any]) -> str:
    for key in ("text", "message", "body", "attributedBody"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value
    message = _dict(row.get("message"))
    for key in ("text", "body"):
        value = message.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _message_is_from_me(row: dict[str, Any]) -> bool:
    for key in ("isFromMe", "is_from_me", "fromMe", "from_me"):
        if key in row:
            return _truthy(row.get(key))
    return False


def _message_ref_hash(row: dict[str, Any], index: int) -> str:
    raw_ref = (
        row.get("guid")
        or row.get("id")
        or row.get("message_id")
        or f"message-index:{index}:{_message_body_text(row)}"
    )
    return hashlib.sha256(str(raw_ref).encode("utf-8")).hexdigest()


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    return False
