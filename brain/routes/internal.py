"""Internal LLM tool-call endpoint — POST /v1/internal/complete.

A side-effect-free local-model completion for trusted service identities
(scope ``llm:complete``). Unlike ``/v1/ask`` this route does NO memory write,
NO embedding, and NO RLS memory-context build — it is a thin, auditable pass
through to the local Ollama primitive.

Logging is metadata-only (issuer, model, latency, token counts, status). Prompt
and response text are NEVER logged (privacy).
"""

from __future__ import annotations

import time
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from brain.core.models import LOCAL_CHAT, LOCAL_CODE
from brain.middleware.jwt_auth import require_auth
from brain.middleware.scopes import check_scopes
from brain.services.ollama_client import generate
from jarvis_common.logging_config import get_logger

router = APIRouter(prefix="/v1/internal", tags=["internal"])
logger = get_logger("alpha_brain")

# Only these local models may be requested. Anything else → 400.
ALLOWED_MODELS = frozenset({LOCAL_CHAT, LOCAL_CODE})

_REQUIRED_SCOPE = "llm:complete"


class CompleteRequest(BaseModel):
    model: str
    prompt: str
    format: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None


class Tokens(BaseModel):
    prompt: int
    completion: int


class CompleteResponse(BaseModel):
    model: str
    result: str
    latency_ms: int
    tokens: Tokens


@router.post("/complete", response_model=CompleteResponse)
async def complete(body: CompleteRequest, request: Request) -> CompleteResponse:
    require_auth(request)
    check_scopes(request, _REQUIRED_SCOPE)

    if body.model not in ALLOWED_MODELS:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "model not allowed",
                "allowed": sorted(ALLOWED_MODELS),
            },
        )

    issuer = str(getattr(request.state, "iss", "unknown"))

    # TODO(ADR): per-issuer cap — enforce a rate limit here keyed on `issuer`.
    # For now we only observe (log-only); no cap is applied.

    options: dict[str, Any] = {}
    if body.temperature is not None:
        options["temperature"] = body.temperature
    if body.max_tokens is not None:
        options["num_predict"] = body.max_tokens

    start = time.monotonic()
    try:
        data = await generate(
            model=body.model,
            prompt=body.prompt,
            format=body.format,
            options=options or None,
        )
    except httpx.HTTPError:
        latency_ms = int((time.monotonic() - start) * 1000)
        logger.warning(
            "internal_complete",
            extra={
                "event": "internal_complete",
                "issuer": issuer,
                "model": body.model,
                "latency_ms": latency_ms,
                "status": "error",
            },
        )
        raise HTTPException(
            status_code=503,
            detail={"error": "llm backend unavailable"},
        ) from None

    latency_ms = int((time.monotonic() - start) * 1000)
    result_text = str(data.get("response", ""))
    prompt_tokens = int(data.get("prompt_eval_count", 0) or 0)
    completion_tokens = int(data.get("eval_count", 0) or 0)

    logger.info(
        "internal_complete",
        extra={
            "event": "internal_complete",
            "issuer": issuer,
            "model": body.model,
            "latency_ms": latency_ms,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "status": "ok",
        },
    )

    return CompleteResponse(
        model=body.model,
        result=result_text,
        latency_ms=latency_ms,
        tokens=Tokens(prompt=prompt_tokens, completion=completion_tokens),
    )
