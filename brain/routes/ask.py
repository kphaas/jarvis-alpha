import time
import httpx
from uuid import NAMESPACE_DNS, UUID, uuid5
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from jarvis_common.logging_config import get_logger
from brain.core.config import ALPHA_NODE, OLLAMA_URL
from brain.core.models import EMBED_MODEL
from brain.db.rls import rls_connection
from brain.memory.memory import MemoryService
from brain.routing.router import route
from brain.services.vault_recall import (
    embed_vault_query,
    search_vault_chunks,
    vault_context_block,
)


router = APIRouter(prefix="/v1", tags=["ask"])
logger = get_logger("alpha_brain")
DEFAULT_VAULT_WORKSPACE_ID = "personal"


def _user_uuid(user_id: str) -> UUID:
    try:
        return UUID(user_id)
    except ValueError:
        return uuid5(NAMESPACE_DNS, user_id)


def _principal_id(request: Request) -> str:
    return str(getattr(request.state, "user_id", None) or "anon")


def _can_read_vault(request: Request) -> bool:
    actor_type = getattr(request.state, "actor_type", "user")
    role = getattr(request.state, "role", None)
    if actor_type == "user" and role == "admin":
        return True
    scopes = set(getattr(request.state, "scopes", []) or [])
    return "*" in scopes or "vault.read" in scopes


def _ensure_vault_workspace(request: Request) -> None:
    workspace_id = getattr(request.state, "workspace_id", None)
    if isinstance(workspace_id, str) and workspace_id.strip():
        request.state.workspace_id = workspace_id.strip()
        return
    request.state.workspace_id = DEFAULT_VAULT_WORKSPACE_ID


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
        vault_embedding = None
        if _can_read_vault(request):
            _ensure_vault_workspace(request)
            vault_embedding = await embed_vault_query(body.prompt)
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
            vault_context = ""
            if _can_read_vault(request):
                try:
                    vault_matches = await search_vault_chunks(
                        conn,
                        query=body.prompt,
                        embedding=vault_embedding,
                        limit=5,
                    )
                    vault_context = vault_context_block(vault_matches)
                except Exception as exc:
                    logger.warning("vault recall unavailable for ask: %s", exc)

        enriched_prompt = body.prompt
        context_blocks = []
        if context:
            context_blocks.append(f"Context from memory:\n{context}")
        if vault_context:
            context_blocks.append(vault_context)
        if context_blocks:
            enriched_prompt = "\n\n".join(context_blocks) + f"\n\nUser: {body.prompt}"

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
