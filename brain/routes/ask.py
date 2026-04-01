import time

from fastapi import APIRouter
from pydantic import BaseModel, Field

from brain.core.config import ALPHA_NODE
from brain.db.session import get_db
from brain.routing.router import route

router = APIRouter(prefix="/v1", tags=["ask"])


class AskRequest(BaseModel):
    prompt: str
    mode: str = Field(
        default="auto",
        description="auto, local, claude, gemini, perplexity, council",
    )


class AskResponse(BaseModel):
    mode: str
    result: str
    refined_prompt: str | None = None
    claude_response: str | None = None
    gemini_response: str | None = None
    synthesis: str | None = None
    steps_completed: int | None = None
    error: str | None = None


def _response_summary(result_dict: dict) -> str:
    text = result_dict.get("result") or result_dict.get("final_answer") or ""
    return text[:200]


def _to_ask_response(result_dict: dict) -> AskResponse:
    payload = {k: v for k, v in result_dict.items() if k in AskResponse.model_fields}
    res = payload.get("result")
    if not res:
        res = result_dict.get("final_answer") or ""
    payload["result"] = res if isinstance(res, str) else str(res or "")
    payload.setdefault("mode", result_dict.get("mode", ""))
    for key in AskResponse.model_fields:
        if key not in payload:
            payload[key] = None
    if payload.get("mode") is None:
        payload["mode"] = ""
    return AskResponse(**payload)


async def _log_ask(
    conn,
    *,
    start_time: float,
    status_code: int,
    result_dict: dict,
) -> None:
    latency_ms = int((time.monotonic() - start_time) * 1000)
    await conn.execute(
        """
        INSERT INTO jarvis_request_log
          (trace_id, user_id, node, route, method, status_code, latency_ms, model, error)
        VALUES
          (gen_random_uuid(), $1, $2, $3, $4, $5, $6, $7, $8)
        """,
        "anon",
        ALPHA_NODE,
        "/v1/ask",
        "POST",
        status_code,
        latency_ms,
        result_dict.get("mode", "unknown"),
        result_dict.get("error", None),
    )


@router.post("/ask", response_model=AskResponse)
async def ask(body: AskRequest) -> AskResponse:
    start_time = time.monotonic()
    try:
        result_dict = await route(body.prompt, body.mode)
        async with get_db("anon") as conn:
            await _log_ask(
                conn,
                start_time=start_time,
                status_code=200,
                result_dict=result_dict,
            )
        return _to_ask_response(result_dict)
    except Exception as e:
        err = str(e)
        try:
            async with get_db("anon") as conn:
                await _log_ask(
                    conn,
                    start_time=start_time,
                    status_code=500,
                    result_dict={"mode": body.mode, "error": err},
                )
        except Exception:
            pass
        return AskResponse(mode=body.mode, result="", error=err)
