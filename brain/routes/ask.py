import time
import httpx
from uuid import NAMESPACE_DNS, UUID, uuid5
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from jarvis_common.logging_config import get_logger
from brain.core.config import ALPHA_NODE, OLLAMA_URL
from brain.core.models import EMBED_MODEL
from brain.db.rls import rls_connection
from brain.memory.memory import MemoryService
from brain.memory.semantic_commands import (
    MemoryFactValidationError,
    memory_save_response_text,
    parse_memory_command,
)
from brain.routing.router import route


router = APIRouter(prefix="/v1", tags=["ask"])
logger = get_logger("alpha_brain")


def _user_uuid(user_id: str) -> UUID:
    try:
        return UUID(user_id)
    except ValueError:
        return uuid5(NAMESPACE_DNS, user_id)


def _principal_id(request: Request) -> str:
    return str(getattr(request.state, "user_id", None) or "anon")


class AskRequest(BaseModel):
    prompt: str
    mode: str = Field(
        default="auto",
        description="auto, local, claude, gemini, perplexity, council",
    )
    session_id: str = "default"
    workspace_id: str | None = None
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
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{OLLAMA_URL}/api/embeddings",
                json={"model": EMBED_MODEL, "prompt": text},
            )
            resp.raise_for_status()
            return resp.json()["embedding"]
    except Exception as e:
        logger.warning("embedding failed: %s (len=%d)", e, len(text))
        return []


async def _log_ask(
    *,
    request: Request,
    user_id: str,
    start_time: float,
    status_code: int,
    result_dict: dict,
) -> None:
    latency_ms = int((time.monotonic() - start_time) * 1000)
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
            "/v1/ask",
            "POST",
            status_code,
            latency_ms,
            result_dict.get("mode", "unknown"),
            result_dict.get("error", None),
        )


@router.post("/ask", response_model=AskResponse)
async def ask(body: AskRequest, request: Request) -> AskResponse:
    memory = MemoryService()

    try:
        memory_command = parse_memory_command(body.prompt)
    except MemoryFactValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.detail) from exc

    if memory_command is not None:
        from brain.middleware.scopes import check_scopes

        check_scopes(request, "memory.write", "admin")
        uid = _user_uuid(getattr(request.state, "user_id", None) or "anon")
        async with rls_connection(request) as conn:
            result = await memory.save_semantic(
                conn=conn,
                user_id=uid,
                fact=memory_command.fact,
                category=memory_command.category,
                provenance={
                    "source_surface": "ask_pages",
                    "source_route": "/v1/ask",
                    "source_session_id": body.session_id,
                    "source_action": "slash_memory_command",
                    "actor_type": str(
                        getattr(request.state, "actor_type", "user") or "user"
                    ),
                    "actor_role": str(getattr(request.state, "role", "user") or "user"),
                },
            )
        return AskResponse(
            mode="system",
            result=memory_save_response_text(
                saved=bool(result.get("saved")),
                category=memory_command.category,
                reason=result.get("reason"),
                review_required=result.get("review_required"),
            ),
        )

    # Handle /forget command
    if body.prompt.strip().lower().startswith("/forget"):
        from brain.middleware.scopes import check_scopes

        check_scopes(request, "memory.write", "admin")
        topic = body.prompt.strip()[7:].strip()
        uid = _user_uuid(getattr(request.state, "user_id", None) or "anon")
        async with rls_connection(request) as conn:
            if topic:
                deleted = await memory.forget_by_topic(conn, uid, topic)
                return AskResponse(
                    mode="system",
                    result=f"🗑️ Forgot memories related to '{topic}'. (DELETE {deleted})",
                )
            else:
                deleted = await memory.forget_working(conn, uid)
                return AskResponse(
                    mode="system",
                    result=f"🗑️ Cleared all working memory. (DELETE {deleted})",
                )

    start_time = time.monotonic()
    try:
        embedding = await _embed(body.prompt)
        raw_user_id = _principal_id(request)
        uid = _user_uuid(raw_user_id)

        async with rls_connection(request) as conn:
            context = await memory.build_context(
                conn=conn,
                user_id=uid,
                prompt=body.prompt,
                session_id=body.session_id,
                embedding=embedding,
                principal_id=raw_user_id,
            )

        enriched_prompt = body.prompt
        if context:
            enriched_prompt = f"Context from memory:\n{context}\n\nUser: {body.prompt}"

        result_dict = await route(enriched_prompt, body.mode)

        result_text = result_dict.get("result", "")
        result_embedding = await _embed(result_text) if result_text else []

        if result_text:
            async with rls_connection(request) as conn:
                await memory.store(
                    conn=conn,
                    user_id=uid,
                    session_id=body.session_id,
                    summary=body.prompt,
                    role="user",
                    embedding=embedding,
                    persistent=body.persistent,
                )
                await memory.store(
                    conn=conn,
                    user_id=uid,
                    session_id=body.session_id,
                    summary=result_text,
                    role="assistant",
                    embedding=result_embedding,
                    persistent=body.persistent,
                )

        await _log_ask(
            request=request,
            user_id=(getattr(request.state, "user_id", None) or "anon"),
            start_time=start_time,
            status_code=200,
            result_dict=result_dict,
        )
        return AskResponse(**result_dict)

    except Exception as e:
        err = str(e)
        try:
            await _log_ask(
                request=request,
                user_id=(getattr(request.state, "user_id", None) or "anon"),
                status_code=500,
                start_time=start_time,
                result_dict={"mode": body.mode, "error": err},
            )
        except Exception:
            pass
        return AskResponse(mode=body.mode, result="", error=err)
