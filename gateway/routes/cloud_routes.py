import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from html.parser import HTMLParser
from importlib import import_module
from typing import Any
from urllib.parse import urldefrag, urljoin

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


class AnthropicAdminRequest(BaseModel):
    path: str
    params: dict[str, str]


class GoogleBillingRequest(BaseModel):
    currency_code: str = "USD"


class InternetSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    count: int = Field(default=5, ge=1, le=10)
    provider: str = "brave"


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
    if req.provider != "brave":
        raise HTTPException(status_code=400, detail="unsupported search provider")

    api_key = _secret_or_none("BRAVE_SEARCH_API_KEY") or _secret_or_none(
        "BRAVE_API_KEY"
    )
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="Brave Search API key not configured",
        )

    count = min(max(req.count, 1), 10)
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": req.query, "count": count},
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

    payload: object = response.json()
    web = payload.get("web") if isinstance(payload, dict) else None
    raw_results = web.get("results") if isinstance(web, dict) else None
    if not isinstance(raw_results, list):
        raw_results = []

    results: list[dict[str, object]] = []
    for item in raw_results[:count]:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        title = item.get("title")
        description = item.get("description")
        if not isinstance(url, str):
            continue
        safety = validate_url(url)
        if not safety.allowed or not safety.normalized_url or not safety.host:
            continue
        sanitized = sanitize_untrusted_text(
            description if isinstance(description, str) else "",
            max_chars=1000,
        )
        results.append(
            {
                "title": title if isinstance(title, str) else None,
                "url": safety.normalized_url,
                "host": safety.host,
                "description": sanitized.text,
                "risk_markers": sanitized.risk_markers,
            }
        )

    return {
        "provider": "brave",
        "query_hash": _hash_text(req.query),
        "fetched_at": datetime.now(UTC).isoformat(),
        "results": results,
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
