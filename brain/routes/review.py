"""POST /v1/review — Brain-hosted code review endpoint for Forge (TASK-001 Deliverable A).

Forge service POSTs a code diff plus acceptance criteria; this endpoint dispatches
to local Ollama, parses a structured per-criterion verdict, and returns it.

Per-route auth: only service JWTs with the forge.llm.call scope are accepted.
Current production Forge calls use the Sandbox service identity (iss=sandbox);
the future dedicated Forge identity (iss=forge) is accepted too.

Request log row written to jarvis_request_log on every call. A row in
alpha_cloud_costs is NOT written today because that table's provider CHECK
constraint is limited to ('anthropic','gemini','perplexity') — local Ollama
calls cost $0 and have no provider value the table accepts. A follow-up task
should expand the CHECK to include 'ollama' if we want compute attribution
for local-model calls.
"""

from __future__ import annotations

import json
import time

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from brain.core.config import ALPHA_NODE, OLLAMA_URL
from brain.core.models import LOCAL_CODE
from brain.db.rls import rls_connection
from jarvis_common.logging_config import get_logger

router = APIRouter(prefix="/v1", tags=["review"])
logger = get_logger("alpha_brain")

DEFAULT_MODEL = LOCAL_CODE
OLLAMA_TIMEOUT_S = 60.0
REVIEW_SERVICE_ISSUERS = frozenset({"sandbox", "forge"})
REQUIRED_SCOPE = "forge.llm.call"


class ReviewRequest(BaseModel):
    spec_id: str
    code_diff: str
    acceptance_criteria: list[str] = Field(default_factory=list)
    model: str | None = None


class CriterionVerdict(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    criterion: str
    pass_: bool = Field(alias="pass")
    notes: str = ""


class ReviewResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    spec_id: str
    overall_verdict: str
    criteria: list[CriterionVerdict]
    model: str
    duration_s: float
    error: str | None = None


def _assert_review_service(
    *,
    iss: str | None,
    actor_type: str | None,
    scopes: list[str] | tuple[str, ...] | None,
) -> None:
    caller_scopes = list(scopes or [])
    if (
        actor_type != "service"
        or iss not in REVIEW_SERVICE_ISSUERS
        or REQUIRED_SCOPE not in caller_scopes
    ):
        logger.warning(
            "review_403 iss=%s actor_type=%s required_scope=%s",
            iss,
            actor_type,
            REQUIRED_SCOPE,
        )
        raise HTTPException(
            status_code=403,
            detail={
                "error": "forbidden",
                "required_actor_type": "service",
                "required_iss": sorted(REVIEW_SERVICE_ISSUERS),
                "required_scope": REQUIRED_SCOPE,
                "your_iss": iss,
                "your_actor_type": actor_type,
                "your_scopes": caller_scopes,
            },
        )


def _build_prompt(spec_id: str, code_diff: str, criteria: list[str]) -> str:
    criteria_block = (
        "\n".join(f"{i + 1}. {c}" for i, c in enumerate(criteria)) or "(none)"
    )
    return (
        "You are a strict code reviewer. Evaluate the code diff against each "
        "acceptance criterion. Return ONLY a JSON object — no prose, no markdown "
        "fences, no commentary.\n\n"
        f"Spec ID: {spec_id}\n\n"
        f"Acceptance criteria:\n{criteria_block}\n\n"
        f"Code diff:\n{code_diff}\n\n"
        "Required JSON shape:\n"
        '{"criteria": [{"criterion": "<text>", "pass": true|false, "notes": "<short>"}, ...]}\n'
    )


def _strip_fences(text: str) -> str:
    s = text.strip()
    if not s.startswith("```"):
        return s
    after_open = s.split("\n", 1)
    s = after_open[1] if len(after_open) == 2 else ""
    if s.lower().startswith("json\n"):
        s = s[5:]
    if s.rstrip().endswith("```"):
        s = s.rstrip()[:-3]
    return s.strip()


def _parse_review_response(raw: str) -> list[CriterionVerdict]:
    """Parse Ollama's response into per-criterion verdicts.

    Raises ValueError if unparseable or missing the 'criteria' array.
    """
    text = _strip_fences(raw)
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"reviewer returned non-JSON: {e}") from e
    items = obj.get("criteria") if isinstance(obj, dict) else None
    if not isinstance(items, list):
        raise ValueError("reviewer JSON missing 'criteria' list")
    parsed: list[CriterionVerdict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        parsed.append(
            CriterionVerdict(
                criterion=str(item.get("criterion", "")),
                **{"pass": bool(item.get("pass", False))},
                notes=str(item.get("notes", "")),
            )
        )
    return parsed


def _overall_verdict(criteria: list[CriterionVerdict]) -> str:
    if not criteria:
        return "warn"
    if all(c.pass_ for c in criteria):
        return "pass"
    return "fail"


async def _call_ollama(prompt: str, model: str) -> str:
    payload = {"model": model, "prompt": prompt, "stream": False}
    try:
        async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT_S) as client:
            resp = await client.post(f"{OLLAMA_URL}/api/generate", json=payload)
            resp.raise_for_status()
            return resp.json().get("response", "")
    except httpx.TimeoutException as e:
        logger.warning("review_ollama_timeout model=%s", model)
        raise HTTPException(
            status_code=504,
            detail={"error": "ollama_timeout", "model": model},
        ) from e
    except httpx.HTTPError as e:
        logger.warning("review_ollama_http_error model=%s err=%s", model, e)
        raise HTTPException(
            status_code=502,
            detail={"error": "ollama_bad_gateway", "model": model},
        ) from e


async def _log_review(
    *,
    request: Request,
    start_time: float,
    status_code: int,
    model: str,
    error: str | None,
) -> None:
    latency_ms = int((time.monotonic() - start_time) * 1000)
    user_id = getattr(request.state, "user_id", None) or "forge-review"
    try:
        async with rls_connection(request) as conn:
            await conn.execute(
                """
                INSERT INTO jarvis_request_log
                  (trace_id, user_id, node, route, method, status_code, latency_ms, model, error)
                VALUES
                  (gen_random_uuid(), $1, $2, $3, $4, $5, $6, $7, $8)
                """,
                user_id,
                ALPHA_NODE,
                "/v1/review",
                "POST",
                status_code,
                latency_ms,
                model,
                error,
            )
    except Exception as log_err:
        logger.warning("review_log_failed err=%s", log_err)


@router.post("/review", response_model=ReviewResponse, response_model_by_alias=True)
async def review(body: ReviewRequest, request: Request) -> ReviewResponse:
    _assert_review_service(
        iss=getattr(request.state, "iss", None),
        actor_type=getattr(request.state, "actor_type", None),
        scopes=getattr(request.state, "scopes", []),
    )
    model = body.model or DEFAULT_MODEL
    start_time = time.monotonic()
    log_status = 200
    log_error: str | None = None
    try:
        prompt = _build_prompt(body.spec_id, body.code_diff, body.acceptance_criteria)
        raw = await _call_ollama(prompt, model)
        try:
            parsed = _parse_review_response(raw)
        except ValueError as parse_err:
            log_status = 502
            log_error = f"parse_failed: {parse_err}"
            return ReviewResponse(
                spec_id=body.spec_id,
                overall_verdict="warn",
                criteria=[],
                model=model,
                duration_s=round(time.monotonic() - start_time, 3),
                error=log_error,
            )
        return ReviewResponse(
            spec_id=body.spec_id,
            overall_verdict=_overall_verdict(parsed),
            criteria=parsed,
            model=model,
            duration_s=round(time.monotonic() - start_time, 3),
        )
    except HTTPException as e:
        log_status = e.status_code
        log_error = str(e.detail)
        raise
    finally:
        await _log_review(
            request=request,
            start_time=start_time,
            status_code=log_status,
            model=model,
            error=log_error,
        )
