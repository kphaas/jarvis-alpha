import hmac
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
import httpx
from pydantic import BaseModel
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
    service_account_info: dict[str, Any]
    account_id: str
    currency_code: str = "USD"


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
        scopes = ["https://www.googleapis.com/auth/cloud-billing.readonly"]
        creds = service_account.Credentials.from_service_account_info(
            req.service_account_info,
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
            f"https://cloudbilling.googleapis.com/v1/billingAccounts/{req.account_id}/reports",
            params={"currency_code": req.currency_code},
            headers={"Authorization": f"Bearer {token}"},
        )
    if response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Google Billing HTTP {response.status_code}",
        )
    return {"payload": response.json()}
