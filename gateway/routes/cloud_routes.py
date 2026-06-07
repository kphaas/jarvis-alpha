import hmac
import json
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from html.parser import HTMLParser
from importlib import import_module
from typing import Any
from urllib.parse import quote, urldefrag, urljoin

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
from jarvis_common.logging_config import get_logger
from jarvis_common.secrets import get_secret

logger = get_logger("alpha_gateway")
router = APIRouter(prefix="/v1/cloud", tags=["cloud"])

_adapters = {
    "claude": ClaudeAdapter(),
    "perplexity": PerplexityAdapter(),
    "gemini": GeminiAdapter(),
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


class AnthropicAdminRequest(BaseModel):
    path: str
    params: dict[str, str]


class GoogleBillingRequest(BaseModel):
    currency_code: str = "USD"


class InternetSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    count: int = Field(default=5, ge=1, le=10)
    provider: str = "auto"


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


_SEARCH_PROVIDERS = ("brave", "perplexity")
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
    if req.provider not in {"auto", "brave", "perplexity"}:
        raise HTTPException(status_code=400, detail="unsupported search provider")

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


@router.post("/internet/health")
async def internet_health(authorization: str = Header(...)):
    """Return Gateway-owned Beacon provider health without exposing secrets."""
    _authorize_gateway_call(authorization)
    providers = [_search_provider_health(provider) for provider in _SEARCH_PROVIDERS]
    configured = [provider for provider in providers if provider["configured"]]
    usable = [
        provider
        for provider in providers
        if provider["configured"] and not provider["circuit_open"]
    ]
    return {
        "status": "ok" if usable else "degraded",
        "provider_order": list(_configured_search_provider_order()),
        "providers": providers,
        "configured_provider_count": len(configured),
        "usable_provider_count": len(usable),
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
    if requested_provider in {"brave", "perplexity"}:
        key = _search_provider_key(requested_provider)
        if not key:
            raise HTTPException(
                status_code=503,
                detail=f"{requested_provider.title()} Search API key not configured",
            )
        if _is_search_provider_circuit_open(requested_provider):
            raise HTTPException(
                status_code=503,
                detail=f"{requested_provider.title()} Search circuit is open",
            )
        return [_SearchProviderCredential(provider=requested_provider, api_key=key)]

    candidates: list[_SearchProviderCredential] = []
    for provider in _configured_search_provider_order():
        key = _search_provider_key(provider)
        if key and not _is_search_provider_circuit_open(provider):
            candidates.append(_SearchProviderCredential(provider=provider, api_key=key))
    return candidates


def _configured_search_provider_order() -> tuple[str, ...]:
    raw = os.getenv("BEACON_SEARCH_PROVIDER_ORDER", "brave,perplexity")
    ordered: list[str] = []
    for item in raw.split(","):
        provider = item.strip().lower()
        if provider in _SEARCH_PROVIDERS and provider not in ordered:
            ordered.append(provider)
    return tuple(ordered or _SEARCH_PROVIDERS)


def _search_provider_key(provider: str) -> str | None:
    if provider == "brave":
        return _secret_or_none("BRAVE_SEARCH_API_KEY") or _secret_or_none(
            "BRAVE_API_KEY"
        )
    if provider == "perplexity":
        return _secret_or_none("PERPLEXITY_API_KEY")
    return None


def _search_provider_health(provider: str) -> dict[str, object]:
    circuit = _SEARCH_CIRCUITS[provider]
    cooldown_remaining_s = (
        max(0, int(circuit.open_until - time.monotonic()))
        if _is_search_provider_circuit_open(provider)
        else None
    )
    return {
        "provider": provider,
        "configured": _search_provider_key(provider) is not None,
        "circuit_open": cooldown_remaining_s is not None,
        "failure_count": len(circuit.failures),
        "cooldown_remaining_seconds": cooldown_remaining_s,
    }


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
