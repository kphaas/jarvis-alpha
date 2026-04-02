import time
import httpx
from uuid import NAMESPACE_DNS, UUID, uuid5
from fastapi import APIRouter
from pydantic import BaseModel, Field
from brain.core.config import ALPHA_NODE, OLLAMA_URL
from brain.core.models import EMBED_MODEL
from brain.db.session import get_db
from brain.db.pool import get_pool
from brain.memory.memory import MemoryService
from brain.routing.router import route

router = APIRouter(prefix="/v1", tags=["ask"])


def _user_uuid(user_id: str) -> UUID:
    try:
        return UUID(user_id)
    except ValueError:
        return uuid5(NAMESPACE_DNS, user_id)


class AskRequest(BaseModel):
    prompt: str
    mode: str = Field(
        default="auto",
        description="auto, local, claude, gemini, perplexity, council",
    )
    session_id: str = "default"
    workspace_id: str | None = None
    user_id: str = "anon"
    persistent: bool = False


class AskResponse(BaseModel):
    mode: str
    result: str
    refined_prompt: str | None = None
    claude_response: str | None = None
    gemini_response: str | None = None
    synthesis: str | None = None
    steps_completed: int | None = None
    error: str | None = None


async def _embed(text: str) -> list[float]:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{OLLAMA_URL}/api/embeddings",
                json={"model": EMBED_MODEL, "prompt": text},
            )
            resp.raise_for_status()
            return resp.json()["embedding"]
    except Exception:
        return []


async def _log_ask(
    *,
    user_id: str,
    start_time: float,
    status_code: int,
    result_dict: dict,
) -> None:
    latency_ms = int((time.monotonic() - start_time) * 1000)
    async with get_db(user_id) as conn:
        await conn.execute(
            """
            INSERT INTO jarvis_request_log
              (trace_id, user_id, node, route, method, status_code, latency_ms, model, error)
            VALUES
              (gen_random_uuid(), $1, $2, $3, $4, $5, $6, $7, $8)
            """,
            user_id,
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
        pool = get_pool()
        memory = MemoryService(pool)

        embedding = await _embed(body.prompt)
        uid = _user_uuid(body.user_id)

        context = await memory.build_context(
            user_id=uid,
            prompt=body.prompt,
            session_id=body.session_id,
            embedding=embedding,
        )

        enriched_prompt = body.prompt
        if context:
            enriched_prompt = f"Context from memory:\n{context}\n\nUser: {body.prompt}"

        result_dict = await route(enriched_prompt, body.mode)

        result_text = result_dict.get("result", "")
        result_embedding = await _embed(result_text) if result_text else []

        await memory.store(
            user_id=uid,
            session_id=body.session_id,
            summary=body.prompt,
            role="user",
            embedding=embedding,
            persistent=body.persistent,
        )
        await memory.store(
            user_id=uid,
            session_id=body.session_id,
            summary=result_text,
            role="assistant",
            embedding=result_embedding,
            persistent=body.persistent,
        )

        await _log_ask(
            user_id=body.user_id,
            start_time=start_time,
            status_code=200,
            result_dict=result_dict,
        )
        return AskResponse(**result_dict)

    except Exception as e:
        err = str(e)
        try:
            await _log_ask(
                user_id=body.user_id,
                status_code=500,
                start_time=start_time,
                result_dict={"mode": body.mode, "error": err},
            )
        except Exception:
            pass
        return AskResponse(mode=body.mode, result="", error=err)
