from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import asyncpg

from brain.db.pool import get_pool
from brain.services.gmail_client import GmailClient, GmailClientError, GmailConfigError

DEFAULT_TEST_TOKEN_DAYS = 7


@dataclass(frozen=True)
class GmailOAuthHealth:
    id: str | None
    status: str
    checked_at: datetime | None
    last_successful_refresh_at: datetime | None
    token_expires_in: int | None
    scope: str | None
    error_type: str | None
    error_subtype: str | None
    error_message: str | None
    oauth_mode: str
    refresh_token_issued_at: datetime | None
    refresh_token_expires_at: datetime | None
    refresh_token_days_remaining: int | None
    reconnect_recommended: bool


def _oauth_mode() -> str:
    return (
        os.environ.get("ALPHA_GMAIL_OAUTH_MODE", "testing").strip().lower() or "testing"
    )


def _test_token_days() -> int:
    try:
        return max(
            1,
            int(os.environ.get("ALPHA_GMAIL_TEST_TOKEN_DAYS", DEFAULT_TEST_TOKEN_DAYS)),
        )
    except ValueError:
        return DEFAULT_TEST_TOKEN_DAYS


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _safe_error_message(exc: Exception) -> str:
    message = str(exc).replace("\n", " ").strip()
    if isinstance(exc, GmailClientError) and exc.error_description:
        message = exc.error_description.replace("\n", " ").strip()
    return message[:240] or exc.__class__.__name__


def _issued_at() -> datetime | None:
    return _parse_dt(os.environ.get("ALPHA_GMAIL_REFRESH_TOKEN_ISSUED_AT"))


def _expires_at(issued_at: datetime | None, oauth_mode: str) -> datetime | None:
    if oauth_mode != "testing" or issued_at is None:
        return None
    return issued_at + timedelta(days=_test_token_days())


def _days_remaining(expires_at: datetime | None, now: datetime) -> int | None:
    if expires_at is None:
        return None
    seconds = (expires_at - now).total_seconds()
    return max(0, int(seconds // 86400))


def _health_from_row(row: asyncpg.Record | None) -> GmailOAuthHealth | None:
    if row is None:
        return None
    now = datetime.now(timezone.utc)
    mode = _oauth_mode()
    issued_at = _issued_at()
    expires_at = _expires_at(issued_at, mode)
    days_remaining = _days_remaining(expires_at, now)
    status = row["status"]
    return GmailOAuthHealth(
        id=str(row["id"]),
        status=status,
        checked_at=row["checked_at"],
        last_successful_refresh_at=row["last_successful_refresh_at"],
        token_expires_in=row["token_expires_in"],
        scope=row["scope"],
        error_type=row["error_type"],
        error_subtype=row["error_subtype"],
        error_message=row["error_message"],
        oauth_mode=mode,
        refresh_token_issued_at=issued_at,
        refresh_token_expires_at=expires_at,
        refresh_token_days_remaining=days_remaining,
        reconnect_recommended=status != "ok" or days_remaining in {0, 1},
    )


async def latest_gmail_oauth_health(
    conn: asyncpg.Connection,
) -> GmailOAuthHealth | None:
    row = await conn.fetchrow(
        """
        SELECT id, status, checked_at, last_successful_refresh_at,
               token_expires_in, scope, error_type, error_subtype, error_message
        FROM public.alpha_gmail_oauth_health
        ORDER BY checked_at DESC
        LIMIT 1
        """
    )
    return _health_from_row(row)


async def record_gmail_oauth_check(
    conn: asyncpg.Connection,
    *,
    status: str,
    trigger: str,
    token_expires_in: int | None = None,
    scope: str | None = None,
    error_type: str | None = None,
    error_subtype: str | None = None,
    error_message: str | None = None,
) -> GmailOAuthHealth:
    row = await conn.fetchrow(
        """
        INSERT INTO public.alpha_gmail_oauth_health (
            status, trigger, last_successful_refresh_at, token_expires_in, scope,
            error_type, error_subtype, error_message
        )
        VALUES (
            $1, $2,
            CASE WHEN $1 = 'ok' THEN now() ELSE NULL END,
            $3, $4, $5, $6, $7
        )
        RETURNING id, status, checked_at, last_successful_refresh_at,
                  token_expires_in, scope, error_type, error_subtype, error_message
        """,
        status,
        trigger,
        token_expires_in,
        scope,
        error_type,
        error_subtype,
        error_message,
    )
    health = _health_from_row(row)
    if health is None:
        raise RuntimeError("Gmail OAuth health insert did not return a row")
    return health


async def check_gmail_oauth_health(*, trigger: str = "api") -> GmailOAuthHealth:
    pool = get_pool()
    try:
        payload = await GmailClient().refresh_access_token_payload()
    except (GmailClientError, GmailConfigError) as exc:
        async with pool.acquire() as conn:
            return await record_gmail_oauth_check(
                conn,
                status="failed",
                trigger=trigger,
                error_type=getattr(exc, "error_type", None) or exc.__class__.__name__,
                error_subtype=getattr(exc, "error_subtype", None),
                error_message=_safe_error_message(exc),
            )

    async with pool.acquire() as conn:
        return await record_gmail_oauth_check(
            conn,
            status="ok",
            trigger=trigger,
            token_expires_in=_int_or_none(payload.get("expires_in")),
            scope=_str_or_none(payload.get("scope")),
        )


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _str_or_none(value: Any) -> str | None:
    return str(value) if value is not None else None
