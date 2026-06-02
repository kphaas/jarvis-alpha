"""Pluggable alert sinks for JARVIS Alpha.

Interface:
    class IAlertSink:
        async def send(severity, title, message, metadata=None) -> bool

Concrete implementations:
    MattermostWebhookSink — Phase 1 ChatOps sink (incoming webhook)
    MattermostSink  — bot REST sink for Phase 2+ API automation
    PushoverSink    — fallback wake-up sink (curl + asyncio.to_thread)
    NullSink        — logs only, no network (dev/test default)
    CompositeSink   — fan-out to multiple sinks
    FallbackSink    — primary first, fallback only on failure

Factory:
    build_default_sink() -> IAlertSink
        Reads MATTERMOST_* and PUSHOVER_* from env.
        Mattermost primary, Pushover fallback, NullSink if neither configured.

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

MATTERMOST_SEVERITY_VISUALS = {
    Severity.DEBUG: ("🔎", "DEBUG"),
    Severity.INFO: ("ℹ️", "INFO"),
    Severity.WARNING: ("⚠️", "WARNING"),
    Severity.ERROR: ("🚨", "ERROR"),
    Severity.CRITICAL: ("🔥", "CRITICAL"),
}


def _mattermost_alert_message(severity: Severity, title: str, message: str) -> str:
    icon, label = MATTERMOST_SEVERITY_VISUALS[severity]
    return "\n".join(
        [
            f"{icon} **{title[:250]}**",
            f"`{label}` · `JARVIS Gateway`",
            "",
            message[:4000],
            "",
            f"Severity: `{severity.value}`",
        ]
    )


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


class MattermostSink(IAlertSink):
    """Mattermost bot REST sink for Phase 2+ API automation."""

    def __init__(self, base_url: str, bot_token: str, channel_id: str):
        if not base_url or not bot_token or not channel_id:
            raise ValueError("MattermostSink requires base_url, bot_token, channel_id")
        if not base_url.startswith(("https://", "http://")):
            raise ValueError("Mattermost base_url must include http(s) scheme")
        if len(bot_token) < 20:
            raise ValueError("Mattermost bot token is too short")
        if len(channel_id) < 8:
            raise ValueError("Mattermost channel_id is too short")
        self._base_url = base_url.rstrip("/")
        self._bot_token = bot_token
        self._channel_id = channel_id

    @property
    def name(self) -> str:
        return "mattermost"

    def _post_sync(self, payload: dict[str, Any]) -> tuple[int, str]:
        args = [
            "curl",
            "-sS",
            "-m",
            "10",
            "-X",
            "POST",
            "-H",
            "Content-Type: application/json",
            "-H",
            f"Authorization: Bearer {self._bot_token}",
            "-d",
            json.dumps(payload),
            f"{self._base_url}/api/v4/posts",
        ]
        try:
            result = subprocess.run(args, capture_output=True, text=True, timeout=15)
            return result.returncode, result.stdout
        except subprocess.TimeoutExpired:
            return 124, '{"message":"timeout"}'
        except Exception as e:
            return 1, json.dumps({"message": str(e)})

    async def send(
        self,
        severity: Severity,
        title: str,
        message: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> bool:
        payload = {
            "channel_id": self._channel_id,
            "message": _mattermost_alert_message(severity, title, message),
            "props": {
                "jarvis": {
                    "severity": severity.value,
                    "metadata": metadata or {},
                }
            },
        }

        try:
            rc, body = await asyncio.to_thread(self._post_sync, payload)
            if rc != 0:
                log.error("mattermost curl rc=%d body=%s", rc, body[:500])
                return False
            try:
                parsed = json.loads(body)
            except json.JSONDecodeError:
                log.error("mattermost non-JSON response: %s", body[:500])
                return False
            if parsed.get("id"):
                log.info(
                    "mattermost sent severity=%s title=%r post=%s",
                    severity.value,
                    title,
                    parsed.get("id"),
                )
                return True
            log.error("mattermost rejected: %s", parsed)
            return False
        except Exception as e:
            log.error("mattermost send failed: %s", e)
            return False


class MattermostWebhookSink(IAlertSink):
    """Mattermost incoming webhook sink. This is the Phase 1 default."""

    def __init__(self, webhook_url: str, channel_name: str = "alerts"):
        if not webhook_url:
            raise ValueError("MattermostWebhookSink requires webhook_url")
        if not webhook_url.startswith(("https://", "http://")):
            raise ValueError("Mattermost webhook_url must include http(s) scheme")
        if not channel_name:
            raise ValueError("Mattermost channel_name is required")
        self._webhook_url = webhook_url
        self._channel_name = channel_name.lstrip("#")

    @property
    def name(self) -> str:
        return "mattermost-webhook"

    def _post_sync(self, payload: dict[str, Any]) -> tuple[int, str]:
        args = [
            "curl",
            "-sS",
            "-m",
            "10",
            "-X",
            "POST",
            "-H",
            "Content-Type: application/json",
            "-d",
            json.dumps(payload),
            self._webhook_url,
        ]
        try:
            result = subprocess.run(args, capture_output=True, text=True, timeout=15)
            return result.returncode, result.stdout
        except subprocess.TimeoutExpired:
            return 124, "timeout"
        except Exception as e:
            return 1, str(e)

    async def send(
        self,
        severity: Severity,
        title: str,
        message: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> bool:
        payload = {
            "channel": _mattermost_channel_for(severity, self._channel_name),
            "text": _mattermost_alert_message(severity, title, message),
            "props": {
                "jarvis": {
                    "severity": severity.value,
                    "metadata": metadata or {},
                }
            },
        }

        try:
            rc, body = await asyncio.to_thread(self._post_sync, payload)
            if rc != 0:
                log.error("mattermost webhook curl rc=%d body=%s", rc, body[:500])
                return False
            if body.strip() == "ok":
                log.info(
                    "mattermost webhook sent severity=%s title=%r channel=%s",
                    severity.value,
                    title,
                    payload["channel"],
                )
                return True
            log.error("mattermost webhook rejected: %s", body[:500])
            return False
        except Exception as e:
            log.error("mattermost webhook send failed: %s", e)
            return False


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


class FallbackSink(IAlertSink):
    """Try primary first, then fallback only when primary delivery fails."""

    def __init__(self, primary: IAlertSink, fallback: IAlertSink):
        self._primary = primary
        self._fallback = fallback

    @property
    def name(self) -> str:
        return f"fallback({self._primary.name}->{self._fallback.name})"

    async def send(
        self,
        severity: Severity,
        title: str,
        message: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> bool:
        if await self._primary.send(severity, title, message, metadata):
            return True
        log.warning(
            "primary alert sink[%s] failed; trying fallback[%s]",
            self._primary.name,
            self._fallback.name,
        )
        return await self._fallback.send(severity, title, message, metadata)


def build_default_sink() -> IAlertSink:
    """Factory — reads env once, returns configured sink.

    Selection:
        Mattermost webhook + Pushover configured → webhook with Pushover fallback
        Mattermost webhook configured → MattermostWebhookSink
        Mattermost bot REST configured → MattermostSink
        Pushover configured → PushoverSink
        Otherwise → NullSink
    """
    mattermost_webhook_url = (
        os.environ.get("MATTERMOST_WEBHOOK_URL_ALPHA_EVENTS", "").strip()
        or os.environ.get("MATTERMOST_WEBHOOK_URL_ALERTS", "").strip()
        or os.environ.get("MATTERMOST_WEBHOOK_URL", "").strip()
    )
    mattermost_channel_name = (
        os.environ.get("MATTERMOST_CHANNEL_ALERTS_NAME", "").strip() or "alerts"
    )
    mattermost_url = os.environ.get("MATTERMOST_URL", "").strip()
    mattermost_token = os.environ.get("MATTERMOST_BOT_TOKEN", "").strip()
    mattermost_channel = (
        os.environ.get("MATTERMOST_CHANNEL_ALERTS_ID", "").strip()
        or os.environ.get("MATTERMOST_DEFAULT_CHANNEL_ID", "").strip()
    )
    user_key = os.environ.get("PUSHOVER_USER_KEY", "").strip()
    app_token = os.environ.get("PUSHOVER_APP_TOKEN", "").strip()

    mattermost_sink: IAlertSink | None = None
    if mattermost_webhook_url:
        try:
            mattermost_sink = MattermostWebhookSink(
                webhook_url=mattermost_webhook_url,
                channel_name=mattermost_channel_name,
            )
            log.info("alert sink: MattermostWebhookSink configured")
        except ValueError as e:
            log.error(
                "MattermostWebhookSink construction failed, falling back if possible: %s",
                e,
            )
    elif mattermost_url and mattermost_token and mattermost_channel:
        try:
            mattermost_sink = MattermostSink(
                base_url=mattermost_url,
                bot_token=mattermost_token,
                channel_id=mattermost_channel,
            )
            log.info("alert sink: MattermostSink configured")
        except ValueError as e:
            log.error(
                "MattermostSink construction failed, falling back if possible: %s", e
            )

    pushover_sink: IAlertSink | None = None
    if user_key and app_token:
        try:
            pushover_sink = PushoverSink(user_key=user_key, app_token=app_token)
            log.info("alert sink: PushoverSink configured")
        except ValueError as e:
            log.error(
                "PushoverSink construction failed, falling back to NullSink: %s", e
            )

    if mattermost_sink and pushover_sink:
        return FallbackSink(mattermost_sink, pushover_sink)
    if mattermost_sink:
        return mattermost_sink
    if pushover_sink:
        return pushover_sink

    log.warning("alert sink: no Mattermost/Pushover config available; using NullSink")
    return NullSink()


def _mattermost_channel_for(severity: Severity, default_channel: str) -> str:
    if severity in {Severity.ERROR, Severity.CRITICAL}:
        return "alerts"
    return default_channel.lstrip("#")
