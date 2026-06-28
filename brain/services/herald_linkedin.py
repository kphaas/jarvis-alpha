from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from brain.config.secrets import get_secret
from brain.services.gateway_egress import GatewayEgressError, call_gateway_proxy


class HeraldLinkedInConfigError(RuntimeError):
    pass


class HeraldLinkedInPublishError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class HeraldLinkedInIngestDisabled(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class HeraldLinkedInPublishResult:
    status_code: int
    provider_post_urn: str | None
    published_url: str | None


@dataclass(frozen=True, slots=True)
class HeraldLinkedInComment:
    provider_item_urn: str | None
    provider_post_urn: str
    item_url: str | None
    author_name: str
    item_text: str


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
        raise HeraldLinkedInConfigError(f"{name} is not configured")
    return value


def linkedin_ingest_enabled() -> bool:
    return (_secret("HERALD_LINKEDIN_INGEST_ENABLED", "false") or "").lower() in {
        "1",
        "true",
        "yes",
    }


class HeraldLinkedInClient:
    def __init__(
        self,
        *,
        access_token: str | None = None,
        author_urn: str | None = None,
        linkedin_version: str | None = None,
    ) -> None:
        self.access_token = access_token or _required_secret(
            "AT0_LINKEDIN_ACCESS_TOKEN"
        )
        self.author_urn = author_urn or _required_secret("AT0_LINKEDIN_AUTHOR_URN")
        self.linkedin_version = linkedin_version or _secret(
            "AT0_LINKEDIN_API_VERSION", "202606"
        )

    async def publish_text(self, text: str) -> HeraldLinkedInPublishResult:
        clean = " ".join(text.split()).strip()
        if not clean:
            raise HeraldLinkedInPublishError("linkedin_post_text_empty")
        if len(clean) > 3000:
            raise HeraldLinkedInPublishError("linkedin_post_text_too_long")
        try:
            response = await call_gateway_proxy(
                "linkedin/member_post",
                {
                    "access_token": self.access_token,
                    "author_urn": self.author_urn,
                    "linkedin_version": self.linkedin_version,
                    "text": clean,
                },
                timeout_s=35,
            )
        except GatewayEgressError as exc:
            raise HeraldLinkedInPublishError(f"LinkedIn publish failed: {exc}") from exc

        status_code = int(response.get("status_code") or 502)
        if status_code not in {200, 201}:
            raise HeraldLinkedInPublishError(
                f"LinkedIn publish failed: {status_code}",
                status_code=status_code,
            )
        return HeraldLinkedInPublishResult(
            status_code=status_code,
            provider_post_urn=_optional_str(response.get("post_urn")),
            published_url=_optional_str(response.get("post_url")),
        )

    async def list_comments(
        self,
        *,
        post_urn: str,
        limit: int = 25,
    ) -> list[HeraldLinkedInComment]:
        if not linkedin_ingest_enabled():
            raise HeraldLinkedInIngestDisabled("linkedin_ingest_disabled")
        clean_urn = _clean_urn(post_urn)
        try:
            response = await call_gateway_proxy(
                "linkedin/member_post_comments",
                {
                    "access_token": self.access_token,
                    "linkedin_version": self.linkedin_version,
                    "post_urn": clean_urn,
                    "count": max(1, min(int(limit), 50)),
                },
                timeout_s=35,
            )
        except GatewayEgressError as exc:
            raise HeraldLinkedInPublishError(
                f"LinkedIn comments failed: {exc}"
            ) from exc

        status_code = int(response.get("status_code") or 502)
        if status_code != 200:
            raise HeraldLinkedInPublishError(
                f"LinkedIn comments failed: {status_code}",
                status_code=status_code,
            )
        payload = response.get("payload")
        elements = payload.get("elements") if isinstance(payload, dict) else None
        if not isinstance(elements, list):
            return []
        return [_comment_from_payload(item, post_urn=clean_urn) for item in elements]

    async def publish_comment(
        self,
        *,
        post_urn: str,
        text: str,
    ) -> HeraldLinkedInPublishResult:
        clean = " ".join(text.split()).strip()
        if not clean:
            raise HeraldLinkedInPublishError("linkedin_comment_text_empty")
        if len(clean) > 3000:
            raise HeraldLinkedInPublishError("linkedin_comment_text_too_long")
        clean_urn = _clean_urn(post_urn)
        try:
            response = await call_gateway_proxy(
                "linkedin/member_comment",
                {
                    "access_token": self.access_token,
                    "author_urn": self.author_urn,
                    "linkedin_version": self.linkedin_version,
                    "post_urn": clean_urn,
                    "text": clean,
                },
                timeout_s=35,
            )
        except GatewayEgressError as exc:
            raise HeraldLinkedInPublishError(f"LinkedIn comment failed: {exc}") from exc

        status_code = int(response.get("status_code") or 502)
        if status_code not in {200, 201}:
            raise HeraldLinkedInPublishError(
                f"LinkedIn comment failed: {status_code}",
                status_code=status_code,
            )
        return HeraldLinkedInPublishResult(
            status_code=status_code,
            provider_post_urn=_optional_str(response.get("comment_urn")),
            published_url=_optional_str(response.get("comment_url")),
        )


async def publish_linkedin_text(text: str) -> HeraldLinkedInPublishResult:
    return await HeraldLinkedInClient().publish_text(text)


async def fetch_linkedin_comments(
    *,
    post_urn: str,
    limit: int = 25,
) -> list[HeraldLinkedInComment]:
    return await HeraldLinkedInClient().list_comments(post_urn=post_urn, limit=limit)


async def publish_linkedin_comment(
    *,
    post_urn: str,
    text: str,
) -> HeraldLinkedInPublishResult:
    return await HeraldLinkedInClient().publish_comment(post_urn=post_urn, text=text)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _clean_urn(value: str) -> str:
    text = value.strip()
    if not text.startswith("urn:li:"):
        raise HeraldLinkedInPublishError("linkedin_urn_invalid")
    return text[:200]


def _comment_from_payload(
    item: Any,
    *,
    post_urn: str,
) -> HeraldLinkedInComment:
    data = item if isinstance(item, dict) else {}
    message = data.get("message") if isinstance(data.get("message"), dict) else {}
    item_text = (
        _optional_str(message.get("text")) or _optional_str(data.get("text")) or ""
    )
    actor = _optional_str(data.get("actor")) or "unknown"
    item_urn = (
        _optional_str(data.get("id"))
        or _optional_str(data.get("entity"))
        or _optional_str(data.get("commentUrn"))
    )
    return HeraldLinkedInComment(
        provider_item_urn=item_urn,
        provider_post_urn=post_urn,
        item_url=None,
        author_name=actor[:160],
        item_text=item_text[:1200],
    )
