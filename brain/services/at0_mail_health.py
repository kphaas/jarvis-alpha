from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import asyncpg

from brain.db.pool import get_pool
from brain.services.at0_mail_graph_client import (
    At0MailConfigError,
    At0MailGraphClient,
    At0MailGraphError,
    configured_mailboxes,
)

DEFAULT_REQUIRED_GRAPH_ROLES = ("Mail.Send",)
DEFAULT_STUCK_SEND_MINUTES = 15


class At0MailHealthError(RuntimeError):
    pass


@dataclass(frozen=True)
class At0MailGraphHealth:
    id: str | None
    status: str
    trigger: str
    checked_at: datetime
    mailboxes_checked: int
    messages_seen: int
    graph_roles: list[str]
    missing_graph_roles: list[str]
    current_send_failures: int
    stuck_sending_count: int
    last_sent_at: datetime | None
    error_type: str | None
    error_message: str | None

    @property
    def requires_attention(self) -> bool:
        return self.status != "ok"


def required_graph_roles(raw: str | None = None) -> tuple[str, ...]:
    value = (
        raw if raw is not None else os.environ.get("AT0_HERALD_REQUIRED_GRAPH_ROLES")
    )
    if not value:
        return DEFAULT_REQUIRED_GRAPH_ROLES
    roles = tuple(item.strip() for item in value.split(",") if item.strip())
    return roles or DEFAULT_REQUIRED_GRAPH_ROLES


def stuck_send_minutes(raw: str | None = None) -> int:
    value = raw if raw is not None else os.environ.get("AT0_HERALD_STUCK_SEND_MINUTES")
    try:
        return max(1, int(value or DEFAULT_STUCK_SEND_MINUTES))
    except ValueError:
        return DEFAULT_STUCK_SEND_MINUTES


def decode_graph_roles(access_token: str) -> list[str]:
    try:
        payload = access_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
    except Exception as exc:
        raise At0MailHealthError("graph_token_claims_unreadable") from exc
    roles = claims.get("roles") or []
    if not isinstance(roles, list):
        return []
    return sorted(str(role) for role in roles if str(role).strip())


async def latest_at0_mail_graph_health(
    conn: asyncpg.Connection,
) -> At0MailGraphHealth | None:
    row = await conn.fetchrow(
        """
        SELECT id, status, trigger, checked_at, mailboxes_checked, messages_seen,
               graph_roles, missing_graph_roles, current_send_failures,
               stuck_sending_count, last_sent_at, error_type, error_message
        FROM public.alpha_at0_mail_graph_health
        ORDER BY checked_at DESC
        LIMIT 1
        """
    )
    return _health_from_row(row)


async def record_at0_mail_graph_health(
    conn: asyncpg.Connection,
    *,
    status: str,
    trigger: str,
    mailboxes_checked: int,
    messages_seen: int,
    graph_roles: list[str],
    missing_graph_roles: list[str],
    current_send_failures: int,
    stuck_sending_count: int,
    last_sent_at: datetime | None,
    error_type: str | None,
    error_message: str | None,
) -> At0MailGraphHealth:
    row = await conn.fetchrow(
        """
        INSERT INTO public.alpha_at0_mail_graph_health (
            status, trigger, mailboxes_checked, messages_seen,
            graph_roles, missing_graph_roles, current_send_failures,
            stuck_sending_count, last_sent_at, error_type, error_message
        )
        VALUES ($1, $2, $3, $4, $5::text[], $6::text[], $7, $8, $9, $10, $11)
        RETURNING id, status, trigger, checked_at, mailboxes_checked, messages_seen,
                  graph_roles, missing_graph_roles, current_send_failures,
                  stuck_sending_count, last_sent_at, error_type, error_message
        """,
        status,
        trigger,
        mailboxes_checked,
        messages_seen,
        graph_roles,
        missing_graph_roles,
        current_send_failures,
        stuck_sending_count,
        last_sent_at,
        error_type,
        _safe_error_message(error_message),
    )
    health = _health_from_row(row)
    if health is None:
        raise RuntimeError("AT-0 mail graph health insert did not return a row")
    return health


async def check_at0_mail_graph_health(
    *,
    trigger: str = "scheduled",
    max_results: int = 1,
    mailboxes: tuple[str, ...] | None = None,
) -> At0MailGraphHealth:
    bounded_max = max(1, min(max_results, 5))
    selected_mailboxes = mailboxes or configured_mailboxes()
    required_roles = set(required_graph_roles())
    status = "ok"
    error_type: str | None = None
    error_message: str | None = None
    graph_roles: list[str] = []
    missing_roles: list[str] = []
    mailboxes_checked = 0
    messages_seen = 0

    try:
        client = At0MailGraphClient()
        token = await client.access_token()
        graph_roles = decode_graph_roles(token)
        missing_roles = sorted(required_roles - set(graph_roles))
        if missing_roles:
            raise At0MailHealthError(
                "missing required Graph role(s): " + ", ".join(missing_roles)
            )
        for mailbox in selected_mailboxes:
            messages = await client.list_messages(
                mailbox=mailbox,
                max_results=bounded_max,
            )
            mailboxes_checked += 1
            messages_seen += len(messages)
    except (At0MailConfigError, At0MailGraphError, At0MailHealthError) as exc:
        status = "failed"
        error_type = getattr(exc, "error_type", None) or exc.__class__.__name__
        error_message = _safe_error_message(str(exc))
    except Exception as exc:
        status = "failed"
        error_type = exc.__class__.__name__
        error_message = _safe_error_message(str(exc))

    pool = get_pool()
    async with pool.acquire() as conn:
        send_state = await _send_state(conn, stuck_after_minutes=stuck_send_minutes())
        current_send_failures = int(send_state["current_send_failures"] or 0)
        stuck_sending_count = int(send_state["stuck_sending_count"] or 0)
        last_sent_at = send_state["last_sent_at"]
        if status == "ok" and (current_send_failures > 0 or stuck_sending_count > 0):
            status = "failed"
            error_type = "At0MailSendStateDegraded"
            error_message = (
                f"current_send_failures={current_send_failures} "
                f"stuck_sending_count={stuck_sending_count}"
            )
        return await record_at0_mail_graph_health(
            conn,
            status=status,
            trigger=trigger,
            mailboxes_checked=mailboxes_checked,
            messages_seen=messages_seen,
            graph_roles=graph_roles,
            missing_graph_roles=missing_roles,
            current_send_failures=current_send_failures,
            stuck_sending_count=stuck_sending_count,
            last_sent_at=last_sent_at,
            error_type=error_type,
            error_message=error_message,
        )


async def _send_state(
    conn: asyncpg.Connection,
    *,
    stuck_after_minutes: int,
) -> asyncpg.Record:
    return await conn.fetchrow(
        """
        SELECT
            count(*) FILTER (WHERE status = 'send_failed')::int
                AS current_send_failures,
            count(*) FILTER (
                WHERE status = 'sending'
                  AND last_send_attempt_at < now() - make_interval(mins => $1)
            )::int AS stuck_sending_count,
            max(sent_at) AS last_sent_at
        FROM public.alpha_at0_mail_draft_proposals
        """,
        max(1, stuck_after_minutes),
    )


def _health_from_row(row: asyncpg.Record | None) -> At0MailGraphHealth | None:
    if row is None:
        return None
    checked_at = row["checked_at"]
    if checked_at.tzinfo is None:
        checked_at = checked_at.replace(tzinfo=UTC)
    return At0MailGraphHealth(
        id=str(row["id"]),
        status=row["status"],
        trigger=row["trigger"],
        checked_at=checked_at,
        mailboxes_checked=row["mailboxes_checked"],
        messages_seen=row["messages_seen"],
        graph_roles=list(row["graph_roles"] or []),
        missing_graph_roles=list(row["missing_graph_roles"] or []),
        current_send_failures=row["current_send_failures"],
        stuck_sending_count=row["stuck_sending_count"],
        last_sent_at=row["last_sent_at"],
        error_type=row["error_type"],
        error_message=row["error_message"],
    )


def _safe_error_message(value: Any) -> str | None:
    if value is None:
        return None
    message = str(value).replace("\n", " ").strip()
    return message[:240] or None
