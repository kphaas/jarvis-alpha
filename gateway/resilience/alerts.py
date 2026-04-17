"""Pluggable alert sinks for JARVIS Alpha.

Interface:
    class IAlertSink:
        async def send(severity, title, message, metadata=None) -> bool

Concrete implementations:
    PushoverSink    — real Pushover HTTP (curl + asyncio.to_thread)
    NullSink        — logs only, no network (dev/test default)
    CompositeSink   — fan-out to multiple sinks

Factory:
    build_default_sink() -> IAlertSink
        Reads PUSHOVER_USER_KEY + PUSHOVER_APP_TOKEN from env.
        If both present → PushoverSink; else → NullSink.

Severity → Pushover priority mapping (per Pushover API):
    DEBUG     = -2  silent
    INFO      = -1  quiet
    WARNING   =  0  normal
    ERROR     =  1  high (bypasses quiet hours)
    CRITICAL  =  2  emergency (requires ack, retries)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Optional

log = logging.getLogger(__name__)


class Severity(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


PUSHOVER_PRIORITY = {
    Severity.DEBUG: -2,
    Severity.INFO: -1,
    Severity.WARNING: 0,
    Severity.ERROR: 1,
    Severity.CRITICAL: 2,
}


class IAlertSink(ABC):
    """Abstract base for all alert sinks."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    async def send(
        self,
        severity: Severity,
        title: str,
        message: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> bool:
        """Send an alert. Returns True on success, False otherwise.

        Implementations must never raise — alert delivery failure should
        not cascade into caller failure. Log and return False instead.
        """
        ...


class NullSink(IAlertSink):
    """Logs-only sink. Default for dev, test, and missing-config environments."""

    @property
    def name(self) -> str:
        return "null"

    async def send(
        self,
        severity: Severity,
        title: str,
        message: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> bool:
        log.info(
            "ALERT[null] severity=%s title=%r message=%r metadata=%s",
            severity.value,
            title,
            message,
            metadata or {},
        )
        return True


class PushoverSink(IAlertSink):
    """Real Pushover sink. Uses curl + asyncio.to_thread per JARVIS invariant."""

    API_URL = "https://api.pushover.net/1/messages.json"

    def __init__(self, user_key: str, app_token: str):
        if not user_key or not app_token:
            raise ValueError("PushoverSink requires non-empty user_key and app_token")
        if len(user_key) != 30 or len(app_token) != 30:
            raise ValueError("Pushover keys must be exactly 30 characters")
        self._user_key = user_key
        self._app_token = app_token

    @property
    def name(self) -> str:
        return "pushover"

    def _post_sync(self, payload: dict[str, str]) -> tuple[int, str]:
        args = ["curl", "-s", "-m", "10"]
        for k, v in payload.items():
            args.extend(["--form-string", f"{k}={v}"])
        args.append(self.API_URL)
        try:
            result = subprocess.run(args, capture_output=True, text=True, timeout=15)
            return result.returncode, result.stdout
        except subprocess.TimeoutExpired:
            return 124, '{"status":0,"errors":["timeout"]}'
        except Exception as e:
            return 1, json.dumps({"status": 0, "errors": [str(e)]})

    async def send(
        self,
        severity: Severity,
        title: str,
        message: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> bool:
        priority = PUSHOVER_PRIORITY.get(severity, 0)
        payload = {
            "token": self._app_token,
            "user": self._user_key,
            "title": title[:250],
            "message": message[:1024],
            "priority": str(priority),
        }
        if priority == 2:
            payload["retry"] = "60"
            payload["expire"] = "3600"

        try:
            rc, body = await asyncio.to_thread(self._post_sync, payload)
            if rc != 0:
                log.error("pushover curl rc=%d body=%s", rc, body[:500])
                return False
            try:
                parsed = json.loads(body)
            except json.JSONDecodeError:
                log.error("pushover non-JSON response: %s", body[:500])
                return False
            if parsed.get("status") == 1:
                log.info(
                    "pushover sent severity=%s title=%r request=%s",
                    severity.value,
                    title,
                    parsed.get("request"),
                )
                return True
            log.error("pushover rejected: %s", parsed)
            return False
        except Exception as e:
            log.error("pushover send failed: %s", e)
            return False


class CompositeSink(IAlertSink):
    """Fan-out to multiple sinks in parallel. Returns True if ANY sink succeeds.

    Future-proof for Pushover + Loki + PagerDuty configurations.
    """

    def __init__(self, sinks: list[IAlertSink]):
        if not sinks:
            raise ValueError("CompositeSink requires at least one sink")
        self._sinks = sinks

    @property
    def name(self) -> str:
        return f"composite({','.join(s.name for s in self._sinks)})"

    async def send(
        self,
        severity: Severity,
        title: str,
        message: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> bool:
        results = await asyncio.gather(
            *(s.send(severity, title, message, metadata) for s in self._sinks),
            return_exceptions=True,
        )
        any_ok = False
        for sink, result in zip(self._sinks, results):
            if isinstance(result, Exception):
                log.error("composite sink[%s] raised: %s", sink.name, result)
            elif result:
                any_ok = True
            else:
                log.warning("composite sink[%s] returned False", sink.name)
        return any_ok


def build_default_sink() -> IAlertSink:
    """Factory — reads env once, returns configured sink.

    Selection:
        PUSHOVER_USER_KEY + PUSHOVER_APP_TOKEN both set and valid → PushoverSink
        Otherwise → NullSink
    """
    user_key = os.environ.get("PUSHOVER_USER_KEY", "").strip()
    app_token = os.environ.get("PUSHOVER_APP_TOKEN", "").strip()

    if user_key and app_token:
        try:
            sink = PushoverSink(user_key=user_key, app_token=app_token)
            log.info("alert sink: PushoverSink configured")
            return sink
        except ValueError as e:
            log.error("PushoverSink construction failed, falling back to NullSink: %s", e)

    log.warning(
        "alert sink: PushoverSink not configured (missing/invalid PUSHOVER_* secrets) — using NullSink"
    )
    return NullSink()
