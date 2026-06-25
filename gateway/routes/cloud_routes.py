import hmac
import json
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from html.parser import HTMLParser
from importlib import import_module
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote, urldefrag, urljoin, urlparse
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request
import httpx
from pydantic import BaseModel, Field
from brain.services.internet_scout.safety import (
    DEFAULT_MAX_CONTENT_BYTES,
    require_safe_content_metadata,
    validate_redirect_chain,
    validate_url,
)
from brain.services.internet_scout.sanitizer import sanitize_untrusted_text
from gateway.adapters import ClaudeAdapter, PerplexityAdapter, GeminiAdapter
from gateway.adapters.beacon_source_search import (
    SUPPORTED_SOURCE_SEARCH_DATA_SOURCE_IDS,
    execute_source_search,
)
from jarvis_common.logging_config import get_logger
from jarvis_common.secrets import get_secret

logger = get_logger("alpha_gateway")
router = APIRouter(prefix="/v1/cloud", tags=["cloud"])

_adapters = {
    "claude": ClaudeAdapter(),
    "perplexity": PerplexityAdapter(),
    "gemini": GeminiAdapter(),
}

_PRIVACY_LIVE_ENABLED_ENV = "PRIVACY_EXECUTOR_LIVE_ENABLED"
_PRIVACY_LIVE_TARGET_ID = "beenverified"
_PRIVACY_LIVE_TARGET_URL = "https://www.beenverified.com/app/optout/search"
_PRIVACY_LIVE_ADAPTER_KIND = "beenverified_web_form_live_preflight"
_PRIVACY_LIVE_ALLOWED_EFFECTS = ["target_http_get"]
_PRIVACY_LIVE_REQUIRED_BLOCKED = {
    "browser_automation",
    "email_send",
    "sms_send",
    "broker_form_submit",
    "pii_payload_submit",
}


class CloudRequest(BaseModel):
    provider: str
    payload: dict


class GithubIssuesRequest(BaseModel):
    owner: str
    repo: str
    state: str = "open"
    labels: str | None = None
    per_page: int = 100


class GoogleOAuthRefreshRequest(BaseModel):
    client_id: str
    client_secret: str
    refresh_token: str
    grant_type: str = "refresh_token"


class GmailListRequest(BaseModel):
    access_token: str
    user_id: str = "me"
    query: str
    max_results: int = 25


class GmailMessageRequest(BaseModel):
    access_token: str
    user_id: str = "me"
    message_id: str
    format: str = "full"


class MicrosoftGraphTokenRequest(BaseModel):
    tenant_id: str
    client_id: str
    client_assertion: str
    scope: str = "https://graph.microsoft.com/.default"


class MicrosoftGraphMailboxMessagesRequest(BaseModel):
    access_token: str
    mailbox: str
    max_results: int = Field(default=25, ge=1, le=50)


class MicrosoftGraphMailboxReplyRequest(BaseModel):
    access_token: str
    mailbox: str
    message_id: str = Field(min_length=1, max_length=2048)
    reply_body: str = Field(min_length=1, max_length=20000)


class AnthropicAdminRequest(BaseModel):
    path: str
    params: dict[str, str]


class GoogleBillingRequest(BaseModel):
    currency_code: str = "USD"


class InternetSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    count: int = Field(default=5, ge=1, le=10)
    provider: str = "auto"


class InternetSourceSearchRequest(BaseModel):
    data_source_id: str = Field(min_length=1, max_length=80)
    query: str = Field(min_length=1, max_length=2000)
    count: int = Field(default=5, ge=1, le=10)


class InternetFetchRequest(BaseModel):
    url: str = Field(min_length=1, max_length=4000)
    max_bytes: int = Field(
        default=DEFAULT_MAX_CONTENT_BYTES, ge=1, le=DEFAULT_MAX_CONTENT_BYTES
    )


class InternetExtractRequest(BaseModel):
    url: str = Field(min_length=1, max_length=4000)
    max_bytes: int = Field(
        default=DEFAULT_MAX_CONTENT_BYTES, ge=1, le=DEFAULT_MAX_CONTENT_BYTES
    )


class InternetCrawlRequest(BaseModel):
    url: str = Field(min_length=1, max_length=4000)
    max_pages: int = Field(default=5, ge=1, le=10)
    max_depth: int = Field(default=1, ge=0, le=2)
    max_bytes: int = Field(
        default=DEFAULT_MAX_CONTENT_BYTES, ge=1, le=DEFAULT_MAX_CONTENT_BYTES
    )


class PrivacyRemovalDryRunRequest(BaseModel):
    schema_version: Literal["privacy_gateway_dry_run.v1"]
    operation: Literal["privacy.removal.submit"]
    mode: Literal["dry_run"]
    egress_owner: Literal["gateway"]
    egress_mode: Literal["gateway_dry_run"]
    outbound_enabled: Literal[False]
    would_send: Literal[False]
    request_id: UUID
    subject_id: UUID
    target_id: str = Field(min_length=1, max_length=200)
    target_category: str = Field(min_length=1, max_length=100)
    target_opt_out_method: str = Field(min_length=1, max_length=100)
    adapter_kind: str = Field(min_length=1, max_length=100)
    authorization_id: UUID
    action_id: UUID | None = None
    request_payload_hash: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    idempotency_key_digest: str = Field(pattern=r"^hmac-sha256:[a-f0-9]{64}$")
    approval_binding: dict[str, object]
    allowed_effects: list[str] = Field(default_factory=list)
    blocked_effects: list[str] = Field(default_factory=list)
    prepared_at: datetime


class PrivacyRemovalLivePreflightRequest(BaseModel):
    schema_version: Literal["privacy_gateway_live_preflight.v1"]
    operation: Literal["privacy.removal.live_preflight"]
    mode: Literal["live_preflight"]
    egress_owner: Literal["gateway"]
    egress_mode: Literal["gateway_live_preflight"]
    live_enabled_requested: Literal[True]
    request_id: UUID
    subject_id: UUID
    target_id: str = Field(min_length=1, max_length=200)
    target_category: str = Field(min_length=1, max_length=100)
    target_opt_out_method: str = Field(min_length=1, max_length=100)
    adapter_kind: str = Field(min_length=1, max_length=100)
    authorization_id: UUID
    action_id: UUID | None = None
    request_payload_hash: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    dry_run_payload_hash: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    idempotency_key_digest: str = Field(pattern=r"^hmac-sha256:[a-f0-9]{64}$")
    approval_binding: dict[str, object]
    allowed_effects: list[str] = Field(default_factory=list)
    blocked_effects: list[str] = Field(default_factory=list)
    prepared_at: datetime


@dataclass(frozen=True, slots=True)
class _FetchedInternetContent:
    url: str
    host: str
    status_code: int
    content_type: str | None
    fetched_at: datetime
    raw_text: str
    text: str
    truncated: bool
    risk_markers: list[str]
    redirect_chain: list[str]


@dataclass(frozen=True, slots=True)
class _SearchProviderCredential:
    provider: str
    api_key: str


@dataclass(slots=True)
class _SearchProviderCircuit:
    failures: list[float]
    open_until: float = 0.0


_SEARCH_PROVIDERS = ("searxng", "brave", "perplexity")
_SEARCH_PROVIDER_DATA_SOURCE_IDS = {
    "searxng": "searxng-metasearch",
    "brave": "brave-search",
    "perplexity": "perplexity-search",
}
_SEARCH_PROVIDER_ALLOWLIST_ENV = "BEACON_SEARCH_PROVIDER_ALLOWLIST"
_SEARCH_CIRCUITS: dict[str, _SearchProviderCircuit] = {
    provider: _SearchProviderCircuit(failures=[]) for provider in _SEARCH_PROVIDERS
}


def _accepted_gateway_tokens() -> list[str]:
    tokens: list[str] = []
    for name in ("GATEWAY_TOKEN", "ALPHA_SERVICE_TOKEN", "ALPHA_BRAIN_SERVICE_TOKEN"):
        try:
            value = get_secret(name).strip()
        except KeyError:
            continue
        if value:
            tokens.append(value)
    return tokens


def _authorize_gateway_call(authorization: str) -> None:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=403, detail="Invalid gateway token")
    presented = authorization[7:]
    if not any(
        hmac.compare_digest(presented, expected)
        for expected in _accepted_gateway_tokens()
    ):
        raise HTTPException(status_code=403, detail="Invalid gateway token")


def _secret_or_none(name: str) -> str | None:
    try:
        value = get_secret(name).strip()
    except KeyError:
        return None
    return value or None


def _allowed_msgraph_mailboxes() -> set[str]:
    raw = os.getenv("AT0_HERALD_MAILBOXES", "hello@at-0.com,support@at-0.com")
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def _require_allowed_msgraph_mailbox(mailbox: str) -> str:
    normalized = mailbox.strip().lower()
    if normalized not in _allowed_msgraph_mailboxes():
        raise HTTPException(status_code=403, detail="Mailbox is not allowed")
    return normalized


@router.post("/call")
async def cloud_call(
    request: Request,
    req: CloudRequest,
    authorization: str = Header(...),
):
    _authorize_gateway_call(authorization)
    adapter = _adapters.get(req.provider)
    if not adapter:
        raise HTTPException(status_code=400, detail=f"unknown provider: {req.provider}")
    idempotency_key = request.headers.get("X-JARVIS-Idempotency-Key")
    try:
        result = await adapter.call(req.payload, idempotency_key=idempotency_key)
        return {"provider": req.provider, "result": result}
    except Exception as e:
        logger.error("cloud_call: provider=%s error=%s", req.provider, e)
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/github/issues")
async def github_issues(
    req: GithubIssuesRequest,
    authorization: str = Header(...),
):
    _authorize_gateway_call(authorization)
    token = get_secret("GITHUB_TOKEN")
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "jarvis-alpha-dev-agent",
    }
    params: dict[str, Any] = {
        "state": req.state,
        "per_page": req.per_page,
    }
    if req.labels:
        params["labels"] = req.labels
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.get(
            f"https://api.github.com/repos/{req.owner}/{req.repo}/issues",
            params=params,
            headers=headers,
        )
    if response.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=f"GitHub API error: HTTP {response.status_code}",
        )
    data = response.json()
    if not isinstance(data, list):
        raise HTTPException(status_code=502, detail="GitHub API returned invalid JSON")
    return {"items": data}


@router.post("/google_oauth/refresh")
async def google_oauth_refresh(
    req: GoogleOAuthRefreshRequest,
    authorization: str = Header(...),
):
    _authorize_gateway_call(authorization)
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": req.client_id,
                "client_secret": req.client_secret,
                "refresh_token": req.refresh_token,
                "grant_type": req.grant_type,
            },
        )
    payload: Any
    try:
        payload = response.json()
    except Exception:
        payload = {"raw": response.text}
    if response.status_code >= 400:
        return {"status_code": response.status_code, "payload": payload}
    return {"status_code": response.status_code, "payload": payload}


@router.post("/gmail/list")
async def gmail_list(
    req: GmailListRequest,
    authorization: str = Header(...),
):
    _authorize_gateway_call(authorization)
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"https://gmail.googleapis.com/gmail/v1/users/{req.user_id}/messages",
            headers={"Authorization": f"Bearer {req.access_token}"},
            params={"q": req.query, "maxResults": req.max_results},
        )
    payload: Any
    try:
        payload = response.json()
    except Exception:
        payload = {"raw": response.text}
    return {"status_code": response.status_code, "payload": payload}


@router.post("/gmail/message")
async def gmail_message(
    req: GmailMessageRequest,
    authorization: str = Header(...),
):
    _authorize_gateway_call(authorization)
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"https://gmail.googleapis.com/gmail/v1/users/{req.user_id}/messages/{req.message_id}",
            headers={"Authorization": f"Bearer {req.access_token}"},
            params={"format": req.format},
        )
    payload: Any
    try:
        payload = response.json()
    except Exception:
        payload = {"raw": response.text}
    return {"status_code": response.status_code, "payload": payload}


@router.post("/msgraph/token")
async def msgraph_token(
    req: MicrosoftGraphTokenRequest,
    authorization: str = Header(...),
):
    _authorize_gateway_call(authorization)
    token_url = f"https://login.microsoftonline.com/{req.tenant_id}/oauth2/v2.0/token"
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            token_url,
            data={
                "client_id": req.client_id,
                "scope": req.scope,
                "grant_type": "client_credentials",
                "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
                "client_assertion": req.client_assertion,
            },
        )
    payload: Any
    try:
        payload = response.json()
    except Exception:
        payload = {"raw": response.text}
    return {"status_code": response.status_code, "payload": payload}


@router.post("/msgraph/mailbox_messages")
async def msgraph_mailbox_messages(
    req: MicrosoftGraphMailboxMessagesRequest,
    authorization: str = Header(...),
):
    _authorize_gateway_call(authorization)
    mailbox = _require_allowed_msgraph_mailbox(req.mailbox)
    encoded_mailbox = quote(mailbox, safe="")
    select = ",".join(
        [
            "id",
            "internetMessageId",
            "conversationId",
            "from",
            "subject",
            "receivedDateTime",
            "bodyPreview",
            "webLink",
        ]
    )
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"https://graph.microsoft.com/v1.0/users/{encoded_mailbox}/mailFolders/Inbox/messages",
            headers={"Authorization": f"Bearer {req.access_token}"},
            params={
                "$top": req.max_results,
                "$select": select,
                "$orderby": "receivedDateTime desc",
            },
        )
    payload: Any
    try:
        payload = response.json()
    except Exception:
        payload = {"raw": response.text}
    return {"status_code": response.status_code, "payload": payload}


@router.post("/msgraph/mailbox_reply")
async def msgraph_mailbox_reply(
    req: MicrosoftGraphMailboxReplyRequest,
    authorization: str = Header(...),
):
    _authorize_gateway_call(authorization)
    mailbox = _require_allowed_msgraph_mailbox(req.mailbox)
    encoded_mailbox = quote(mailbox, safe="")
    encoded_message_id = quote(req.message_id, safe="")
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            (
                "https://graph.microsoft.com/v1.0/users/"
                f"{encoded_mailbox}/messages/{encoded_message_id}/reply"
            ),
            headers={
                "Authorization": f"Bearer {req.access_token}",
                "Content-Type": "application/json",
            },
            json={
                "message": {
                    "body": {
                        "contentType": "Text",
                        "content": req.reply_body,
                    }
                }
            },
        )
    payload: Any
    try:
        payload = response.json()
    except Exception:
        payload = {"raw": response.text}
    return {"status_code": response.status_code, "payload": payload}


@router.post("/anthropic_admin")
async def anthropic_admin(
    req: AnthropicAdminRequest,
    authorization: str = Header(...),
):
    _authorize_gateway_call(authorization)
    if req.path not in {
        "/v1/organizations/usage_report/messages",
        "/v1/organizations/cost_report",
    }:
        raise HTTPException(status_code=400, detail="unsupported Anthropic admin path")
    api_key = get_secret("ANTHROPIC_ADMIN_KEY")
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.get(
            f"https://api.anthropic.com{req.path}",
            params=req.params,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
        )
    if response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Anthropic admin HTTP {response.status_code}: {response.text[:500]}",
        )
    return {"payload": response.json()}


@router.post("/google_billing")
async def google_billing(
    req: GoogleBillingRequest,
    authorization: str = Header(...),
):
    _authorize_gateway_call(authorization)
    try:
        from google.auth.transport.requests import Request as GARequest
        from google.oauth2 import service_account
    except ImportError:
        raise HTTPException(status_code=503, detail="google-auth not available")

    try:
        account_id = get_secret("GCP_BILLING_ACCOUNT_ID").strip()
        key_path = get_secret("GCP_BILLING_KEY_PATH").strip()
    except KeyError as exc:
        raise HTTPException(status_code=503, detail=f"{exc.args[0]} not configured")
    if not account_id or not key_path:
        raise HTTPException(status_code=503, detail="GCP billing is not configured")

    try:
        with open(key_path, encoding="utf-8") as f:
            service_account_info = json.load(f)
    except Exception:
        raise HTTPException(status_code=503, detail="GCP billing key is not readable")
    if not isinstance(service_account_info, dict):
        raise HTTPException(status_code=503, detail="GCP billing key is invalid")

    try:
        scopes = ["https://www.googleapis.com/auth/cloud-billing.readonly"]
        creds = service_account.Credentials.from_service_account_info(
            service_account_info,
            scopes=scopes,
        )
        creds.refresh(GARequest())
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Google auth failed: {exc}")
    token = creds.token
    if not token:
        raise HTTPException(status_code=502, detail="Google auth returned no token")

    async with httpx.AsyncClient(timeout=45.0) as client:
        response = await client.get(
            f"https://cloudbilling.googleapis.com/v1/billingAccounts/{account_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
    if response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Google Billing HTTP {response.status_code}",
        )
    return {"payload": response.json()}


@router.post("/internet/search")
async def internet_search(
    req: InternetSearchRequest,
    authorization: str = Header(...),
):
    """Run a provider-backed public web search through Gateway-owned egress."""
    _authorize_gateway_call(authorization)
    if req.provider not in {"auto", *_SEARCH_PROVIDERS}:
        raise HTTPException(status_code=400, detail="unsupported search provider")
    if req.provider != "auto" and req.provider not in _search_provider_allowlist():
        raise HTTPException(status_code=403, detail="search provider not allowlisted")

    count = min(max(req.count, 1), 10)
    candidates = _select_search_provider_candidates(req.provider)
    if not candidates:
        raise HTTPException(
            status_code=503, detail="Search provider key not configured"
        )

    last_error: HTTPException | None = None
    async with httpx.AsyncClient(timeout=20.0) as client:
        for credential in candidates:
            start = time.monotonic()
            try:
                _reserve_search_provider_request(credential.provider)
            except HTTPException as exc:
                last_error = exc
                logger.warning(
                    "beacon_search_provider_budget_blocked provider=%s status_code=%s",
                    credential.provider,
                    exc.status_code,
                )
                if req.provider != "auto":
                    raise
                continue

            try:
                results = await _execute_search_provider(
                    client=client,
                    credential=credential,
                    query=req.query,
                    count=count,
                )
            except HTTPException as exc:
                last_error = exc
                _record_search_provider_failure(credential.provider)
                logger.warning(
                    "beacon_search_provider_failed provider=%s status_code=%s",
                    credential.provider,
                    exc.status_code,
                )
                if req.provider != "auto":
                    raise
                continue
            except httpx.HTTPError as exc:
                last_error = HTTPException(
                    status_code=502,
                    detail=f"{credential.provider.title()} Search request failed",
                )
                _record_search_provider_failure(credential.provider)
                logger.warning(
                    "beacon_search_provider_failed provider=%s status_code=%s",
                    credential.provider,
                    last_error.status_code,
                )
                if req.provider != "auto":
                    raise last_error from exc
                continue
            latency_ms = int((time.monotonic() - start) * 1000)
            _record_search_provider_success(credential.provider)
            logger.info(
                "beacon_search_completed provider=%s result_count=%d latency_ms=%d",
                credential.provider,
                len(results),
                latency_ms,
            )
            return {
                "provider": credential.provider,
                "query_hash": _hash_text(req.query),
                "fetched_at": datetime.now(UTC).isoformat(),
                "results": results,
            }

    if last_error is not None:
        raise last_error
    raise HTTPException(status_code=503, detail="Search provider key not configured")


@router.post("/internet/source-search")
async def internet_source_search(
    req: InternetSourceSearchRequest,
    authorization: str = Header(...),
):
    """Run a free/read-only registry source search through Gateway-owned egress."""
    _authorize_gateway_call(authorization)
    data_source_id = req.data_source_id.strip().lower()
    if data_source_id not in SUPPORTED_SOURCE_SEARCH_DATA_SOURCE_IDS:
        raise HTTPException(status_code=400, detail="unsupported Beacon data source")

    count = min(max(req.count, 1), 10)
    start = time.monotonic()
    async with httpx.AsyncClient(timeout=20.0) as client:
        results = await execute_source_search(
            client=client,
            data_source_id=data_source_id,
            query=req.query,
            count=count,
        )
    latency_ms = int((time.monotonic() - start) * 1000)
    logger.info(
        "beacon_source_search_completed data_source_id=%s result_count=%d latency_ms=%d",
        data_source_id,
        len(results),
        latency_ms,
    )
    return {
        "provider": data_source_id,
        "data_source_id": data_source_id,
        "query_hash": _hash_text(req.query),
        "fetched_at": datetime.now(UTC).isoformat(),
        "results": results,
    }


@router.post("/internet/health")
async def internet_health(authorization: str = Header(...)):
    """Return Gateway-owned Beacon provider health without exposing secrets."""
    _authorize_gateway_call(authorization)
    providers = [_search_provider_health(provider) for provider in _SEARCH_PROVIDERS]
    configured = [provider for provider in providers if provider["configured"]]
    usable = [
        provider
        for provider in providers
        if _search_provider_health_is_usable(provider)
    ]
    redundancy = _search_provider_redundancy(len(usable))
    provider_order = _configured_search_provider_names(providers)
    primary_provider = provider_order[0] if provider_order else None
    primary_health = _provider_health_by_name(providers, primary_provider)
    primary_usable = (
        _search_provider_health_is_usable(primary_health)
        if primary_health is not None
        else False
    )
    budget_capped_providers = [
        provider
        for provider in providers
        if provider["configured"] and provider["budget_exhausted"]
    ]
    budget_capped_backup_providers = [
        provider
        for provider in budget_capped_providers
        if provider["provider"] != primary_provider
    ]
    backup_budget_guard_warning = (
        bool(usable)
        and not redundancy["provider_redundancy_ok"]
        and primary_usable
        and bool(budget_capped_backup_providers)
    )
    provider_redundancy_status = (
        "backup_budget_capped"
        if backup_budget_guard_warning
        else redundancy["provider_redundancy_status"]
    )
    status = (
        "ok"
        if usable and redundancy["provider_redundancy_ok"]
        else "warning"
        if backup_budget_guard_warning
        else "degraded"
    )
    return {
        "status": status,
        "provider_order": provider_order,
        "providers": providers,
        "configured_provider_count": len(configured),
        "usable_provider_count": len(usable),
        **redundancy,
        "provider_redundancy_status": provider_redundancy_status,
        "provider_warning_status": "backup_budget_capped"
        if backup_budget_guard_warning
        else None,
        "primary_provider": primary_provider,
        "primary_provider_usable": primary_usable,
        "budget_capped_provider_count": len(budget_capped_providers),
        "budget_capped_backup_provider_count": len(budget_capped_backup_providers),
        "checked_at": datetime.now(UTC).isoformat(),
    }


async def _execute_search_provider(
    *,
    client: httpx.AsyncClient,
    credential: _SearchProviderCredential,
    query: str,
    count: int,
) -> list[dict[str, object]]:
    if credential.provider == "brave":
        raw_results = await _search_brave(
            client=client,
            query=query,
            count=count,
            api_key=credential.api_key,
        )
        return _normalize_search_results(
            raw_results,
            count=count,
            description_keys=("description",),
        )
    if credential.provider == "searxng":
        raw_results = await _search_searxng(
            client=client,
            query=query,
            count=count,
            base_url=credential.api_key,
        )
        return _normalize_search_results(
            raw_results,
            count=count,
            description_keys=("content", "description", "snippet"),
        )
    raw_results = await _search_perplexity(
        client=client,
        query=query,
        count=count,
        api_key=credential.api_key,
    )
    return _normalize_search_results(
        raw_results,
        count=count,
        description_keys=("snippet",),
    )


def _select_search_provider_candidates(
    requested_provider: str,
) -> list[_SearchProviderCredential]:
    if requested_provider in _SEARCH_PROVIDERS:
        if requested_provider not in _search_provider_allowlist():
            raise HTTPException(
                status_code=403,
                detail="search provider not allowlisted",
            )
        key = _search_provider_key(requested_provider)
        if not key:
            raise HTTPException(
                status_code=503,
                detail=_search_provider_not_configured_detail(requested_provider),
            )
        if _is_search_provider_circuit_open(requested_provider):
            raise HTTPException(
                status_code=503,
                detail=f"{_search_provider_display_name(requested_provider)} Search circuit is open",
            )
        return [_SearchProviderCredential(provider=requested_provider, api_key=key)]

    candidates: list[_SearchProviderCredential] = []
    for provider in _configured_search_provider_order():
        key = _search_provider_key(provider)
        if key and not _is_search_provider_circuit_open(provider):
            candidates.append(_SearchProviderCredential(provider=provider, api_key=key))
    return candidates


def _configured_search_provider_order() -> tuple[str, ...]:
    allowlist = _search_provider_allowlist()
    raw = os.getenv("BEACON_SEARCH_PROVIDER_ORDER", "searxng,brave,perplexity")
    ordered: list[str] = []
    for item in raw.split(","):
        provider = item.strip().lower()
        if (
            provider in _SEARCH_PROVIDERS
            and provider in allowlist
            and provider not in ordered
        ):
            ordered.append(provider)
    if ordered:
        return tuple(ordered)
    return tuple(provider for provider in _SEARCH_PROVIDERS if provider in allowlist)


def _search_provider_allowlist() -> frozenset[str]:
    raw = os.getenv(_SEARCH_PROVIDER_ALLOWLIST_ENV)
    if raw is None:
        raw = ",".join(_SEARCH_PROVIDERS)
    return frozenset(
        provider
        for provider in (item.strip().lower() for item in raw.split(","))
        if provider in _SEARCH_PROVIDERS
    )


def _search_provider_key(provider: str) -> str | None:
    if provider == "searxng":
        return _searxng_base_url()
    if provider == "brave":
        return _secret_or_none("BRAVE_SEARCH_API_KEY") or _secret_or_none(
            "BRAVE_API_KEY"
        )
    if provider == "perplexity":
        return _secret_or_none("PERPLEXITY_API_KEY")
    return None


def _searxng_base_url() -> str | None:
    raw = os.getenv("SEARXNG_BASE_URL", "").strip() or _secret_or_none(
        "SEARXNG_BASE_URL"
    )
    if not raw:
        return None
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return raw.rstrip("/")


def _search_provider_display_name(provider: str) -> str:
    if provider == "searxng":
        return "SearXNG"
    if provider == "brave":
        return "Brave"
    if provider == "perplexity":
        return "Perplexity"
    return provider.title()


def _search_provider_not_configured_detail(provider: str) -> str:
    if provider == "searxng":
        return "SearXNG base URL not configured"
    return f"{_search_provider_display_name(provider)} Search API key not configured"


def _search_provider_health(provider: str) -> dict[str, object]:
    circuit = _SEARCH_CIRCUITS[provider]
    cooldown_remaining_s = (
        max(0, int(circuit.open_until - time.monotonic()))
        if _is_search_provider_circuit_open(provider)
        else None
    )
    budget = _search_provider_budget(provider)
    return {
        "provider": provider,
        "data_source_id": _SEARCH_PROVIDER_DATA_SOURCE_IDS[provider],
        "allowlisted": provider in _search_provider_allowlist(),
        "configured": _search_provider_key(provider) is not None,
        "circuit_open": cooldown_remaining_s is not None,
        "failure_count": len(circuit.failures),
        "cooldown_remaining_seconds": cooldown_remaining_s,
        "budget_exhausted": not budget["allowed"],
        "daily_request_count": budget["daily_count"],
        "daily_request_limit": budget["daily_limit"],
        "monthly_request_count": budget["monthly_count"],
        "monthly_request_limit": budget["monthly_limit"],
    }


def _configured_search_provider_names(
    providers: list[dict[str, object]],
) -> list[str]:
    names: list[str] = []
    for provider in _configured_search_provider_order():
        health = _provider_health_by_name(providers, provider)
        if health is not None and bool(health["configured"]):
            names.append(provider)
    return names


def _search_provider_health_is_usable(provider: dict[str, object]) -> bool:
    return bool(
        provider.get("configured")
        and provider.get("allowlisted")
        and not provider.get("circuit_open")
        and not provider.get("budget_exhausted")
    )


def _provider_health_by_name(
    providers: list[dict[str, object]],
    provider_name: str | None,
) -> dict[str, object] | None:
    if provider_name is None:
        return None
    return next(
        (
            provider
            for provider in providers
            if provider.get("provider") == provider_name
        ),
        None,
    )


def _search_provider_redundancy(usable_provider_count: int) -> dict[str, object]:
    required_count = _bounded_int_env(
        "BEACON_MIN_USABLE_SEARCH_PROVIDERS",
        default=2,
        minimum=1,
        maximum=len(_SEARCH_PROVIDERS),
    )
    redundancy_ok = usable_provider_count >= required_count
    if usable_provider_count == 0:
        status = "unavailable"
    elif redundancy_ok:
        status = "redundant"
    else:
        status = "single_provider"
    return {
        "required_provider_count": required_count,
        "provider_redundancy_ok": redundancy_ok,
        "provider_redundancy_status": status,
        "missing_provider_count": max(0, required_count - usable_provider_count),
    }


def _search_usage_dir() -> Path:
    raw = os.getenv("BEACON_SEARCH_USAGE_DIR", "~/jarvis/state/beacon-search-usage")
    path = Path(raw).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _search_usage_path(provider: str) -> Path:
    safe_provider = "".join(
        char for char in provider.lower() if char.isalnum() or char in {"-", "_"}
    )
    return _search_usage_dir() / f"{safe_provider}.json"


def _provider_limit(provider: str, period: str) -> int | None:
    name = f"BEACON_{provider.upper()}_{period.upper()}_SEARCH_LIMIT"
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    try:
        return min(max(int(raw), 0), 1_000_000)
    except ValueError:
        return None


def _load_search_usage(provider: str) -> dict[str, object]:
    today = datetime.now(UTC).date().isoformat()
    month = today[:7]
    path = _search_usage_path(provider)
    try:
        payload = json.loads(path.read_text())
    except (OSError, ValueError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    daily_count = payload.get("daily_count")
    monthly_count = payload.get("monthly_count")
    usage = {
        "day": today,
        "month": month,
        "daily_count": daily_count if isinstance(daily_count, int) else 0,
        "monthly_count": monthly_count if isinstance(monthly_count, int) else 0,
    }
    if payload.get("day") != today:
        usage["daily_count"] = 0
    if payload.get("month") != month:
        usage["monthly_count"] = 0
    return usage


def _save_search_usage(provider: str, usage: dict[str, object]) -> None:
    path = _search_usage_path(provider)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(usage, sort_keys=True))
    tmp_path.replace(path)


def _search_provider_budget(provider: str) -> dict[str, object]:
    usage = _load_search_usage(provider)
    daily_limit = _provider_limit(provider, "daily")
    monthly_limit = _provider_limit(provider, "monthly")
    daily_count = int(usage["daily_count"])
    monthly_count = int(usage["monthly_count"])
    allowed = (daily_limit is None or daily_count < daily_limit) and (
        monthly_limit is None or monthly_count < monthly_limit
    )
    return {
        "allowed": allowed,
        "daily_count": daily_count,
        "daily_limit": daily_limit,
        "monthly_count": monthly_count,
        "monthly_limit": monthly_limit,
    }


def _reserve_search_provider_request(provider: str) -> None:
    usage = _load_search_usage(provider)
    budget = _search_provider_budget(provider)
    if not budget["allowed"]:
        raise HTTPException(
            status_code=429,
            detail=f"{provider.title()} Search budget exhausted",
        )
    usage["daily_count"] = int(usage["daily_count"]) + 1
    usage["monthly_count"] = int(usage["monthly_count"]) + 1
    _save_search_usage(provider, usage)


def _record_search_provider_failure(provider: str) -> None:
    now = time.monotonic()
    circuit = _SEARCH_CIRCUITS[provider]
    window_s = _bounded_int_env(
        "BEACON_SEARCH_CIRCUIT_WINDOW_SECONDS",
        default=300,
        minimum=30,
        maximum=3600,
    )
    threshold = _bounded_int_env(
        "BEACON_SEARCH_CIRCUIT_FAILURE_THRESHOLD",
        default=3,
        minimum=1,
        maximum=20,
    )
    circuit.failures = [
        failed_at for failed_at in circuit.failures if failed_at >= now - window_s
    ]
    circuit.failures.append(now)
    if len(circuit.failures) >= threshold:
        cooldown_s = _bounded_int_env(
            "BEACON_SEARCH_CIRCUIT_COOLDOWN_SECONDS",
            default=300,
            minimum=30,
            maximum=3600,
        )
        circuit.open_until = now + cooldown_s


def _record_search_provider_success(provider: str) -> None:
    circuit = _SEARCH_CIRCUITS[provider]
    circuit.failures = []
    circuit.open_until = 0.0


def _is_search_provider_circuit_open(provider: str) -> bool:
    circuit = _SEARCH_CIRCUITS[provider]
    if not circuit.open_until:
        return False
    if time.monotonic() >= circuit.open_until:
        circuit.open_until = 0.0
        circuit.failures = []
        return False
    return True


def _bounded_int_env(
    name: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return min(max(value, minimum), maximum)


def _select_search_provider(requested_provider: str) -> _SearchProviderCredential:
    candidates = _select_search_provider_candidates(requested_provider)
    if not candidates:
        raise HTTPException(
            status_code=503, detail="Search provider key not configured"
        )
    return candidates[0]


async def _search_brave(
    *,
    client: httpx.AsyncClient,
    query: str,
    count: int,
    api_key: str,
) -> object:
    response = await client.get(
        "https://api.search.brave.com/res/v1/web/search",
        params={"q": query, "count": count},
        headers={
            "X-Subscription-Token": api_key,
            "User-Agent": "jarvis-alpha-beacon/1.0",
        },
    )
    if response.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=f"Brave Search API error: HTTP {response.status_code}",
        )
    try:
        payload: object = response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail="Brave Search API returned invalid JSON",
        ) from exc
    web = payload.get("web") if isinstance(payload, dict) else None
    return web.get("results") if isinstance(web, dict) else None


async def _search_searxng(
    *,
    client: httpx.AsyncClient,
    query: str,
    count: int,
    base_url: str,
) -> object:
    endpoint = urljoin(base_url.rstrip("/") + "/", "search")
    headers = {"User-Agent": "jarvis-alpha-beacon/1.0"}
    api_key = _secret_or_none("SEARXNG_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    response = await client.get(
        endpoint,
        params={
            "q": query,
            "format": "json",
            "language": "en",
            "safesearch": "1",
            "categories": "general",
        },
        headers=headers,
    )
    if response.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=f"SearXNG Search API error: HTTP {response.status_code}",
        )
    try:
        payload: object = response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail="SearXNG Search API returned invalid JSON",
        ) from exc
    return payload.get("results") if isinstance(payload, dict) else None


async def _search_perplexity(
    *,
    client: httpx.AsyncClient,
    query: str,
    count: int,
    api_key: str,
) -> object:
    response = await client.post(
        "https://api.perplexity.ai/search",
        json={
            "query": query,
            "max_results": count,
            "search_context_size": "low",
        },
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "jarvis-alpha-beacon/1.0",
        },
    )
    if response.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=f"Perplexity Search API error: HTTP {response.status_code}",
        )
    try:
        payload: object = response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail="Perplexity Search API returned invalid JSON",
        ) from exc
    return payload.get("results") if isinstance(payload, dict) else None


def _normalize_search_results(
    raw_results: object,
    *,
    count: int,
    description_keys: tuple[str, ...],
) -> list[dict[str, object]]:
    if not isinstance(raw_results, list):
        return []

    results: list[dict[str, object]] = []
    for item in raw_results[:count]:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        title = item.get("title")
        description = _first_string(item, description_keys)
        if not isinstance(url, str):
            continue
        safety = validate_url(url)
        if not safety.allowed or not safety.normalized_url or not safety.host:
            continue
        sanitized = sanitize_untrusted_text(description or "", max_chars=1000)
        results.append(
            {
                "title": title if isinstance(title, str) else None,
                "url": safety.normalized_url,
                "host": safety.host,
                "description": sanitized.text,
                "risk_markers": sanitized.risk_markers,
            }
        )
    return results


def _first_string(item: dict[object, object], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str):
            return value
    return None


@router.post("/privacy/removal/dry-run")
async def privacy_removal_dry_run(
    req: PrivacyRemovalDryRunRequest,
    authorization: str = Header(...),
):
    """Validate a Privacy Agent dry-run envelope without public egress."""
    _authorize_gateway_call(authorization)
    if req.allowed_effects:
        raise HTTPException(
            status_code=400,
            detail="privacy dry-run must not request allowed effects",
        )
    required_blocked = {
        "public_http",
        "browser_automation",
        "email_send",
        "sms_send",
        "broker_form_submit",
    }
    if not required_blocked.issubset(set(req.blocked_effects)):
        raise HTTPException(
            status_code=400,
            detail="privacy dry-run blocked effects incomplete",
        )

    return {
        "status": "dry_run_ready",
        "schema_version": req.schema_version,
        "gateway_path": "/v1/cloud/privacy/removal/dry-run",
        "egress_owner": "gateway",
        "egress_mode": "gateway_dry_run",
        "outbound_enabled": False,
        "would_send": False,
        "request_id": str(req.request_id),
        "target_id": req.target_id,
        "adapter_kind": req.adapter_kind,
        "idempotency_key_digest": req.idempotency_key_digest,
        "accepted_at": datetime.now(UTC).isoformat(),
    }


@router.post("/privacy/removal/live-preflight")
async def privacy_removal_live_preflight(
    req: PrivacyRemovalLivePreflightRequest,
    authorization: str = Header(...),
):
    """Run the one-target Privacy Agent live preflight behind a kill switch."""
    _authorize_gateway_call(authorization)
    _validate_privacy_live_preflight_request(req)

    if not _privacy_live_enabled():
        return _privacy_live_preflight_payload(
            req,
            status="live_disabled",
            outbound_enabled=False,
            target_http_attempted=False,
        )

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            response = await client.get(
                _PRIVACY_LIVE_TARGET_URL,
                headers={"User-Agent": "jarvis-alpha-privacy-preflight/1.0"},
            )
    except httpx.RequestError:
        return _privacy_live_preflight_payload(
            req,
            status="live_preflight_failed",
            outbound_enabled=True,
            target_http_attempted=True,
            failure_class="request_error",
        )

    if response.status_code >= 400:
        return _privacy_live_preflight_payload(
            req,
            status="live_preflight_failed",
            outbound_enabled=True,
            target_http_attempted=True,
            target_http_status_code=response.status_code,
            target_content_type=response.headers.get("content-type"),
        )

    return _privacy_live_preflight_payload(
        req,
        status="live_preflight_passed",
        outbound_enabled=True,
        target_http_attempted=True,
        target_http_status_code=response.status_code,
        target_content_type=response.headers.get("content-type"),
        target_content_length=response.headers.get("content-length"),
    )


def _validate_privacy_live_preflight_request(
    req: PrivacyRemovalLivePreflightRequest,
) -> None:
    if req.target_id != _PRIVACY_LIVE_TARGET_ID:
        raise HTTPException(
            status_code=400,
            detail="privacy live preflight target not allowed",
        )
    if req.target_opt_out_method != "web_form":
        raise HTTPException(
            status_code=400,
            detail="privacy live preflight adapter not available",
        )
    if req.adapter_kind != _PRIVACY_LIVE_ADAPTER_KIND:
        raise HTTPException(
            status_code=400,
            detail="privacy live preflight adapter mismatch",
        )
    if req.allowed_effects != _PRIVACY_LIVE_ALLOWED_EFFECTS:
        raise HTTPException(
            status_code=400,
            detail="privacy live preflight allowed effects invalid",
        )
    if not _PRIVACY_LIVE_REQUIRED_BLOCKED.issubset(set(req.blocked_effects)):
        raise HTTPException(
            status_code=400,
            detail="privacy live preflight blocked effects incomplete",
        )
    binding = req.approval_binding
    if binding.get("approval_status") != "approved":
        raise HTTPException(
            status_code=400,
            detail="privacy live preflight approval not approved",
        )
    for key in (
        "approval_queue_id",
        "approval_decided_at",
        "approval_parameters_hash",
        "approved_action_payload_hash",
    ):
        if not isinstance(binding.get(key), str) or not binding[key]:
            raise HTTPException(
                status_code=400,
                detail="privacy live preflight approval binding incomplete",
            )


def _privacy_live_enabled() -> bool:
    return os.getenv(_PRIVACY_LIVE_ENABLED_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _privacy_live_preflight_payload(
    req: PrivacyRemovalLivePreflightRequest,
    *,
    status: str,
    outbound_enabled: bool,
    target_http_attempted: bool,
    failure_class: str | None = None,
    target_http_status_code: int | None = None,
    target_content_type: str | None = None,
    target_content_length: str | None = None,
) -> dict[str, object]:
    return {
        "status": status,
        "schema_version": req.schema_version,
        "gateway_path": "/v1/cloud/privacy/removal/live-preflight",
        "egress_owner": "gateway",
        "egress_mode": "gateway_live_preflight",
        "outbound_enabled": outbound_enabled,
        "would_send": False,
        "target_http_attempted": target_http_attempted,
        "request_id": str(req.request_id),
        "target_id": req.target_id,
        "target_url": _PRIVACY_LIVE_TARGET_URL,
        "adapter_kind": req.adapter_kind,
        "idempotency_key_digest": req.idempotency_key_digest,
        "failure_class": failure_class,
        "target_http_status_code": target_http_status_code,
        "target_content_type": target_content_type,
        "target_content_length": target_content_length,
        "accepted_at": datetime.now(UTC).isoformat(),
    }


@router.post("/internet/fetch")
async def internet_fetch(
    req: InternetFetchRequest,
    authorization: str = Header(...),
):
    """Fetch one public URL through Gateway-owned egress with Beacon guards."""
    _authorize_gateway_call(authorization)
    fetched = await _fetch_public_content(url=req.url, max_bytes=req.max_bytes)
    return _fetch_payload(fetched)


@router.post("/internet/extract")
async def internet_extract(
    req: InternetExtractRequest,
    authorization: str = Header(...),
):
    """Extract main text from one guarded public URL without trusting page content."""
    _authorize_gateway_call(authorization)
    fetched = await _fetch_public_content(url=req.url, max_bytes=req.max_bytes)
    return _extract_payload(fetched)


@router.post("/internet/crawl")
async def internet_crawl(
    req: InternetCrawlRequest,
    authorization: str = Header(...),
):
    """Crawl same-host public pages with the Beacon guarded fetch/extract path."""
    _authorize_gateway_call(authorization)
    seed = validate_url(req.url)
    if not seed.allowed or seed.normalized_url is None or seed.host is None:
        raise HTTPException(
            status_code=400,
            detail={"error": "unsafe_url", "reasons": seed.reasons},
        )

    pages: list[dict[str, object]] = []
    seen: set[str] = set()
    queued: list[tuple[str, int]] = [(seed.normalized_url, 0)]
    queued_urls = {seed.normalized_url}

    while queued and len(pages) < req.max_pages:
        current_url, depth = queued.pop(0)
        queued_urls.discard(current_url)
        if current_url in seen:
            continue
        seen.add(current_url)

        safety = validate_url(current_url)
        if (
            not safety.allowed
            or safety.normalized_url is None
            or safety.host != seed.host
        ):
            continue

        fetched = await _fetch_public_content(
            url=safety.normalized_url,
            max_bytes=req.max_bytes,
        )
        if fetched.host != seed.host:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "crawl_cross_host_redirect",
                    "seed_host": seed.host,
                    "final_host": fetched.host,
                },
            )

        discovered_links = _discover_same_host_links(
            fetched.raw_text,
            base_url=fetched.url,
            seed_host=seed.host,
        )
        pages.append(
            _crawl_page_payload(
                fetched=fetched,
                depth=depth,
                discovered_links=discovered_links,
            )
        )

        if depth >= req.max_depth:
            continue
        for link in discovered_links:
            if len(pages) + len(queued) >= req.max_pages:
                break
            if link in seen or link in queued_urls:
                continue
            queued.append((link, depth + 1))
            queued_urls.add(link)

    return {
        "seed_url": seed.normalized_url,
        "seed_host": seed.host,
        "fetched_at": datetime.now(UTC).isoformat(),
        "max_pages": req.max_pages,
        "max_depth": req.max_depth,
        "pages": pages,
    }


def _extract_payload(fetched: _FetchedInternetContent) -> dict[str, object]:
    extracted_text, extractor = _extract_main_text(fetched.raw_text)
    extraction_fallback = not extracted_text.strip()
    if extraction_fallback:
        fallback_text = _fallback_text_from_html(fetched.raw_text)
        if fallback_text:
            extracted_text = fallback_text
            extractor = "fallback_html_text"
        else:
            extracted_text = fetched.text
            extractor = "fallback_sanitized_text"

    sanitized = sanitize_untrusted_text(extracted_text)
    risk_markers = sorted(set([*fetched.risk_markers, *sanitized.risk_markers]))
    return {
        "url": fetched.url,
        "host": fetched.host,
        "status_code": fetched.status_code,
        "content_type": fetched.content_type,
        "content_hash": _hash_text(sanitized.text),
        "fetched_at": fetched.fetched_at.isoformat(),
        "extracted_text": sanitized.text,
        "extractor": extractor,
        "extraction_fallback": extraction_fallback,
        "truncated": fetched.truncated or sanitized.truncated,
        "risk_markers": risk_markers,
        "redirect_chain": fetched.redirect_chain,
    }


def _crawl_page_payload(
    *,
    fetched: _FetchedInternetContent,
    depth: int,
    discovered_links: list[str],
) -> dict[str, object]:
    payload = _extract_payload(fetched)
    payload["depth"] = depth
    payload["discovered_links"] = discovered_links[:25]
    return payload


async def _fetch_public_content(
    *,
    url: str,
    max_bytes: int,
) -> _FetchedInternetContent:
    safety = validate_url(url)
    if not safety.allowed or not safety.normalized_url:
        raise HTTPException(
            status_code=400,
            detail={"error": "unsafe_url", "reasons": safety.reasons},
        )

    max_bytes = min(max(max_bytes, 1), DEFAULT_MAX_CONTENT_BYTES)
    async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
        async with client.stream("GET", safety.normalized_url) as response:
            chain = [safety.normalized_url]
            chain.extend(str(history.url) for history in response.history)
            chain.append(str(response.url))
            try:
                redirect_results = validate_redirect_chain(chain)
            except ValueError as exc:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": "unsafe_redirect",
                        "reasons": str(exc).split(", "),
                    },
                ) from exc

            content_type = response.headers.get("content-type")
            content_length = _int_header(response.headers.get("content-length"))
            try:
                require_safe_content_metadata(
                    content_type,
                    content_length,
                    max_bytes=max_bytes,
                )
            except ValueError as exc:
                raise HTTPException(
                    status_code=400,
                    detail={"error": "unsafe_content", "reasons": str(exc).split(", ")},
                ) from exc

            if response.status_code >= 400:
                raise HTTPException(
                    status_code=502,
                    detail=f"Fetch error: HTTP {response.status_code}",
                )

            chunks: list[bytes] = []
            total = 0
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail="Fetched content exceeds Beacon byte cap",
                    )
                chunks.append(chunk)

    final = redirect_results[-1]
    if final.normalized_url is None or final.host is None:
        raise HTTPException(status_code=502, detail="Final URL safety result invalid")

    body = b"".join(chunks)
    raw_text = body.decode("utf-8", errors="replace")
    sanitized = sanitize_untrusted_text(raw_text)
    return _FetchedInternetContent(
        url=final.normalized_url,
        host=final.host,
        status_code=response.status_code,
        content_type=response.headers.get("content-type"),
        fetched_at=datetime.now(UTC),
        raw_text=raw_text,
        text=sanitized.text,
        truncated=sanitized.truncated,
        risk_markers=sanitized.risk_markers,
        redirect_chain=[
            result.normalized_url
            for result in redirect_results
            if result.normalized_url is not None
        ],
    )


def _fetch_payload(fetched: _FetchedInternetContent) -> dict[str, object]:
    return {
        "url": fetched.url,
        "host": fetched.host,
        "status_code": fetched.status_code,
        "content_type": fetched.content_type,
        "content_hash": _hash_text(fetched.text),
        "fetched_at": fetched.fetched_at.isoformat(),
        "text": fetched.text,
        "truncated": fetched.truncated,
        "risk_markers": fetched.risk_markers,
        "redirect_chain": fetched.redirect_chain,
    }


def _extract_main_text(raw_text: str) -> tuple[str, str]:
    try:
        trafilatura = import_module("trafilatura")
        extracted = trafilatura.extract(
            raw_text,
            include_comments=False,
            include_tables=True,
            output_format="txt",
        )
    except ImportError:
        return "", "trafilatura_missing"
    except Exception as exc:
        logger.warning(
            "beacon_extract_failed",
            extra={
                "event": "beacon_extract_failed",
                "extractor": "trafilatura",
                "error_class": exc.__class__.__name__,
            },
        )
        return "", "trafilatura_error"

    if not isinstance(extracted, str) or not extracted.strip():
        return "", "trafilatura_empty"
    return extracted, "trafilatura"


class _HTMLLinkExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag.lower() != "a":
            return
        for name, value in attrs:
            if name.lower() == "href" and value:
                self.links.append(value)


def _discover_same_host_links(
    raw_text: str,
    *,
    base_url: str,
    seed_host: str,
) -> list[str]:
    parser = _HTMLLinkExtractor()
    parser.feed(raw_text)
    parser.close()

    links: list[str] = []
    seen: set[str] = set()
    for raw_href in parser.links:
        href = raw_href.strip()
        if not href:
            continue
        candidate = urldefrag(urljoin(base_url, href)).url
        safety = validate_url(candidate)
        if (
            not safety.allowed
            or safety.normalized_url is None
            or safety.host != seed_host
        ):
            continue
        if safety.normalized_url in seen:
            continue
        links.append(safety.normalized_url)
        seen.add(safety.normalized_url)
        if len(links) >= 25:
            break
    return links


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag.lower() in {"script", "style", "noscript"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        stripped = data.strip()
        if stripped:
            self._parts.append(stripped)

    def text(self) -> str:
        return " ".join(" ".join(self._parts).split())


def _fallback_text_from_html(raw_text: str) -> str:
    parser = _HTMLTextExtractor()
    parser.feed(raw_text)
    parser.close()
    return parser.text()


def _hash_text(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _int_header(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None
