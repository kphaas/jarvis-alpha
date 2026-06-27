from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable

from brain.config.secrets import get_secret
from brain.services.gateway_egress import GatewayEgressError, call_gateway_proxy_sync

INTROSPECTION_PROXY_PATH = "linkedin/token_introspection"
DEFAULT_REQUIRED_SCOPES = ("w_member_social",)
DEFAULT_WARN_DAYS = 14


class HeraldLinkedInHealthError(RuntimeError):
    pass


@dataclass(frozen=True)
class HeraldLinkedInTokenHealth:
    status: str
    checked_at: datetime
    active: bool
    seconds_remaining: int | None
    scopes: list[str]
    missing_scopes: list[str]
    error_type: str | None
    error_message: str | None

    @property
    def requires_attention(self) -> bool:
        return self.status != "ok"


PostGateway = Callable[[str, dict[str, str], int], dict[str, Any]]


def required_scopes(raw: str | None = None) -> tuple[str, ...]:
    value = raw if raw is not None else os.environ.get("AT0_LINKEDIN_REQUIRED_SCOPES")
    if not value:
        return DEFAULT_REQUIRED_SCOPES
    scopes = tuple(item for item in re.split(r"[\s,]+", value.strip()) if item)
    return scopes or DEFAULT_REQUIRED_SCOPES


def warn_seconds(raw: str | None = None) -> int:
    value = raw if raw is not None else os.environ.get("AT0_LINKEDIN_TOKEN_WARN_DAYS")
    try:
        return max(1, int(value or DEFAULT_WARN_DAYS)) * 86400
    except ValueError:
        return DEFAULT_WARN_DAYS * 86400


def check_linkedin_token_health(
    *,
    access_token: str | None = None,
    client_id: str | None = None,
    client_secret: str | None = None,
    now: datetime | None = None,
    post_gateway: PostGateway | None = None,
    timeout_s: int = 15,
) -> HeraldLinkedInTokenHealth:
    checked_at = now or datetime.now(UTC)
    try:
        payload = (post_gateway or _post_gateway_introspection)(
            INTROSPECTION_PROXY_PATH,
            {
                "client_id": client_id or _required_secret("AT0_LINKEDIN_CLIENT_ID"),
                "client_secret": client_secret
                or _required_secret("AT0_LINKEDIN_CLIENT_SECRET"),
                "token": access_token or _required_secret("AT0_LINKEDIN_ACCESS_TOKEN"),
            },
            timeout_s,
        )
        return evaluate_introspection(payload, now=checked_at)
    except Exception as exc:
        return HeraldLinkedInTokenHealth(
            status="failed",
            checked_at=checked_at,
            active=False,
            seconds_remaining=None,
            scopes=[],
            missing_scopes=[],
            error_type=exc.__class__.__name__,
            error_message=_safe_error_message(str(exc)),
        )


def evaluate_introspection(
    payload: dict[str, Any],
    *,
    now: datetime | None = None,
    required: tuple[str, ...] | None = None,
    warn_within_seconds: int | None = None,
) -> HeraldLinkedInTokenHealth:
    checked_at = now or datetime.now(UTC)
    active = bool(payload.get("active"))
    scopes = _scopes(payload.get("scope") or payload.get("scopes"))
    missing = sorted(set(required or required_scopes()) - set(scopes))
    remaining = _seconds_remaining(payload, now=checked_at)

    status = "ok"
    error_type = None
    error_message = None
    if not active:
        status = "failed"
        error_type = "LinkedInTokenInactive"
        error_message = "linkedin token is inactive"
    elif missing:
        status = "failed"
        error_type = "LinkedInTokenMissingScope"
        error_message = "missing required scope(s): " + ", ".join(missing)
    elif remaining is not None and remaining <= 0:
        status = "failed"
        error_type = "LinkedInTokenExpired"
        error_message = "linkedin token is expired"
    elif remaining is not None and remaining <= (warn_within_seconds or warn_seconds()):
        status = "warning"
        error_type = "LinkedInTokenExpiringSoon"
        error_message = f"linkedin token expires in {remaining} seconds"

    return HeraldLinkedInTokenHealth(
        status=status,
        checked_at=checked_at,
        active=active,
        seconds_remaining=remaining,
        scopes=scopes,
        missing_scopes=missing,
        error_type=error_type,
        error_message=error_message,
    )


def _post_gateway_introspection(
    path: str, payload: dict[str, str], timeout_s: int
) -> dict[str, Any]:
    try:
        response = call_gateway_proxy_sync(path, payload, timeout_s=timeout_s)
    except GatewayEgressError as exc:
        raise HeraldLinkedInHealthError("linkedin introspection proxy failed") from exc

    status_code = int(response.get("status_code") or 502)
    if status_code != 200:
        raise HeraldLinkedInHealthError(f"linkedin introspection HTTP {status_code}")
    body = response.get("payload")
    if not isinstance(body, dict):
        raise HeraldLinkedInHealthError("linkedin introspection returned non-object")
    return body


def _seconds_remaining(payload: dict[str, Any], *, now: datetime) -> int | None:
    for key in ("expires_in", "expiresIn", "time_to_live", "timeToLive", "ttl"):
        value = _int_or_none(payload.get(key))
        if value is not None:
            return value

    for key in ("expires_at", "expiresAt", "expiration_time", "expirationTime", "exp"):
        value = payload.get(key)
        epoch = _int_or_none(value)
        if epoch is not None:
            return epoch - int(now.timestamp())
        if isinstance(value, str):
            try:
                dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                continue
            return int((dt.astimezone(UTC) - now).total_seconds())
    return None


def _scopes(value: Any) -> list[str]:
    if isinstance(value, list):
        return sorted(str(item) for item in value if str(item).strip())
    if isinstance(value, str):
        return sorted(item for item in re.split(r"[\s,]+", value.strip()) if item)
    return []


def _required_secret(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        value = get_secret(name)
    clean = value.strip()
    if not clean:
        raise HeraldLinkedInHealthError(f"{name} is not configured")
    return clean


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_error_message(value: str) -> str:
    return " ".join(value.split())[:240]
