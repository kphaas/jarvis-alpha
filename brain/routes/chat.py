"""
chat.py — OpenAI-compatible streaming chat endpoint + thread management.

Routes:
  POST /v1/chat/completions   streaming SSE ask (main UI endpoint)
  GET  /v1/threads            list threads for current user
  PATCH /v1/threads/{id}      rename thread title
  DELETE /v1/threads/{id}     soft-delete (archive) thread
  POST /v1/threads/{id}/escalate  promote to overnight TaskGraph
"""

import json
import time
import asyncio
import httpx
from uuid import UUID, uuid4, uuid5, NAMESPACE_DNS
from typing import AsyncGenerator
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from brain.core.config import OLLAMA_URL
from brain.core.models import EMBED_MODEL, LOCAL_CHAT
from brain.db.pool import get_pool
from brain.memory.memory import MemoryService
from brain.routing.router import route

router = APIRouter(tags=["chat"])

MAX_PERSONAL_THREADS = 7
MAX_PROJECT_THREADS = 5


async def _set_rls_user(conn, user_id: str) -> None:
    await conn.execute("SELECT set_config('rls.user_id', $1, true)", user_id)


# ── Pydantic models ────────────────────────────────────────────────────────────


class CompletionRequest(BaseModel):
    messages: list[dict]
    model: str = Field(
        default="auto", description="auto|local|claude|gemini|perplexity|council"
    )
    council_models: list[str] = Field(
        default=[], description="models for council mode e.g. ['claude','gemini']"
    )
    thread_id: str | None = None
    project_id: int | None = None
    stream: bool = True
    show_council: bool = False


class ThreadPatch(BaseModel):
    title: str


class EscalateRequest(BaseModel):
    reason: str | None = None


# ── Helpers ────────────────────────────────────────────────────────────────────


def _user_id(request: Request) -> str:
    return getattr(request.state, "user_id", "anon")


async def _embed(text: str) -> list[float]:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"{OLLAMA_URL}/api/embeddings",
                json={"model": EMBED_MODEL, "prompt": text},
            )
            r.raise_for_status()
            return r.json()["embedding"]
    except Exception:
        return []


async def _get_or_create_thread(
    pool, user_id: str, thread_id: str | None, project_id: int | None
) -> str:
    async with pool.acquire() as conn:
        await _set_rls_user(conn, user_id)
        if thread_id:
            row = await conn.fetchrow(
                "SELECT id FROM chat_threads WHERE id=$1 AND user_id=$2 AND archived_at IS NULL",
                UUID(thread_id),
                user_id,
            )
            if row:
                return str(row["id"])

        if project_id:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM chat_threads WHERE user_id=$1 AND project_id=$2 AND archived_at IS NULL",
                user_id,
                project_id,
            )
            if count >= MAX_PROJECT_THREADS:
                raise HTTPException(
                    429, f"Max {MAX_PROJECT_THREADS} threads per project"
                )
        else:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM chat_threads WHERE user_id=$1 AND project_id IS NULL AND archived_at IS NULL",
                user_id,
            )
            if count >= MAX_PERSONAL_THREADS:
                raise HTTPException(429, f"Max {MAX_PERSONAL_THREADS} personal threads")

        new_id = uuid4()
        await conn.execute(
            """INSERT INTO chat_threads (id, user_id, project_id)
               VALUES ($1, $2, $3)""",
            new_id,
            user_id,
            project_id,
        )
        return str(new_id)


async def _save_message(
    pool,
    thread_id: str,
    user_id: str,
    role: str,
    content: str,
    model_used: str | None = None,
    council_detail: dict | None = None,
    memory_injected: bool = False,
    latency_ms: int | None = None,
) -> None:
    async with pool.acquire() as conn:
        await _set_rls_user(conn, user_id)
        await conn.execute(
            """INSERT INTO chat_messages
               (thread_id, role, content, model_used, council_detail, memory_injected, latency_ms)
               VALUES ($1,$2,$3,$4,$5::jsonb,$6,$7)""",
            UUID(thread_id),
            role,
            content,
            model_used,
            json.dumps(council_detail) if council_detail else None,
            memory_injected,
            latency_ms,
        )
        await conn.execute(
            "UPDATE chat_threads SET updated_at=now(), model_used=$1 WHERE id=$2",
            model_used,
            UUID(thread_id),
        )


async def _auto_name_thread(
    pool, thread_id: str, user_id: str, first_prompt: str
) -> None:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": LOCAL_CHAT,
                    "prompt": (
                        f"Generate a 3-5 word title for a conversation that starts with: "
                        f'"{first_prompt[:200]}". '
                        "Reply with ONLY the title. No quotes, no punctuation at end."
                    ),
                    "stream": False,
                },
            )
            title = r.json().get("response", "").strip()[:80]
            if title:
                async with pool.acquire() as conn:
                    await _set_rls_user(conn, user_id)
                    await conn.execute(
                        "UPDATE chat_threads SET title=$1, updated_at=now() WHERE id=$2",
                        title,
                        UUID(thread_id),
                    )
    except Exception:
        pass


# ── SSE streaming ──────────────────────────────────────────────────────────────


async def _stream_single(
    prompt: str, mode: str, thread_id: str, model_label: str
) -> AsyncGenerator[str, None]:
    """Stream tokens from router → SSE events."""
    result = await route(prompt, mode)
    text = result.get("result", "")
    model_used = result.get("mode", mode)

    words = text.split(" ")
    for i, word in enumerate(words):
        chunk = word + (" " if i < len(words) - 1 else "")
        event = json.dumps(
            {
                "delta": chunk,
                "model": model_used,
                "thread_id": thread_id,
                "done": False,
            }
        )
        yield f"data: {event}\n\n"
        await asyncio.sleep(0.01)

    yield f"data: {json.dumps({'delta': '', 'model': model_used, 'thread_id': thread_id, 'done': True})}\n\n"
    yield "data: [DONE]\n\n"


async def _stream_council(
    prompt: str, models: list[str], thread_id: str, show_council: bool
) -> AsyncGenerator[str, None]:
    """Parallel council calls → optional per-model stream → synthesis."""
    tasks = {m: asyncio.create_task(route(prompt, m)) for m in models}
    results = {}
    for m, task in tasks.items():
        try:
            results[m] = await task
        except Exception as e:
            results[m] = {"result": f"[{m} error: {e}]", "mode": m}

    if show_council:
        for m, res in results.items():
            meta = json.dumps(
                {"council_model": m, "thread_id": thread_id, "done": False}
            )
            yield f"data: {meta}\n\n"
            for word in res.get("result", "").split(" "):
                chunk = json.dumps(
                    {"delta": word + " ", "council_model": m, "thread_id": thread_id}
                )
                yield f"data: {chunk}\n\n"
                await asyncio.sleep(0.005)

    council_text = "\n\n".join(
        f"[{m.upper()}]: {r.get('result', '')}" for m, r in results.items()
    )
    synth_prompt = (
        f"Synthesize these responses into one clear answer:\n\n{council_text}\n\n"
        f"Original question: {prompt}"
    )
    synth_result = await route(synth_prompt, "local")
    synth_text = synth_result.get("result", "")

    for word in synth_text.split(" "):
        chunk = json.dumps(
            {
                "delta": word + " ",
                "model": "council/synthesis",
                "thread_id": thread_id,
                "done": False,
                "council_detail": {m: r.get("result", "") for m, r in results.items()},
            }
        )
        yield f"data: {chunk}\n\n"
        await asyncio.sleep(0.01)

    yield f"data: {json.dumps({'delta': '', 'model': 'council/synthesis', 'thread_id': thread_id, 'done': True})}\n\n"
    yield "data: [DONE]\n\n"


def _append_sse_delta(delta_parts: list[str], chunk: str) -> None:
    if not chunk.startswith("data: ") or "[DONE]" in chunk:
        return
    line = chunk[6:].strip()
    if not line:
        return
    try:
        payload = json.loads(line)
        if not payload.get("done") and "delta" in payload:
            delta_parts.append(str(payload.get("delta", "")))
    except json.JSONDecodeError:
        pass


# ── Routes ─────────────────────────────────────────────────────────────────────


@router.post("/v1/chat/completions")
async def chat_completions(body: CompletionRequest, request: Request):
    start = time.monotonic()
    user_id = _user_id(request)
    pool = get_pool()
    memory = MemoryService(pool)

    thread_id = await _get_or_create_thread(
        pool, user_id, body.thread_id, body.project_id
    )

    user_msg = next(
        (m["content"] for m in reversed(body.messages) if m.get("role") == "user"), ""
    )

    embedding = await _embed(user_msg)
    uid = uuid5(NAMESPACE_DNS, user_id)

    context = await memory.build_context(
        user_id=uid,
        prompt=user_msg,
        session_id=thread_id,
        embedding=embedding,
    )
    memory_injected = bool(context)
    enriched = (
        f"Context from memory:\n{context}\n\nUser: {user_msg}" if context else user_msg
    )

    await _save_message(pool, thread_id, user_id, "user", user_msg)

    is_new = body.thread_id is None
    if is_new:
        asyncio.create_task(_auto_name_thread(pool, thread_id, user_id, user_msg))

    delta_parts: list[str] = []

    async def _generator():
        is_council = body.model == "council" or len(body.council_models) >= 2
        models = body.council_models if body.council_models else [body.model]

        if is_council:
            gen = _stream_council(enriched, models, thread_id, body.show_council)
        else:
            gen = _stream_single(enriched, body.model, thread_id, body.model)

        async for chunk in gen:
            _append_sse_delta(delta_parts, chunk)
            yield chunk

        latency = int((time.monotonic() - start) * 1000)
        full_text = "".join(delta_parts)
        model_label = "council/synthesis" if is_council else body.model
        council_raw = None

        asyncio.create_task(
            _save_message(
                pool,
                thread_id,
                user_id,
                "assistant",
                full_text,
                model_used=model_label,
                council_detail=council_raw,
                memory_injected=memory_injected,
                latency_ms=latency,
            )
        )
        asyncio.create_task(
            memory.store(
                user_id=uid,
                session_id=thread_id,
                summary=full_text,
                role="assistant",
                embedding=await _embed(full_text),
                persistent=False,
            )
        )

    return StreamingResponse(_generator(), media_type="text/event-stream")


@router.get("/v1/threads")
async def list_threads(request: Request):
    user_id = _user_id(request)
    pool = get_pool()
    async with pool.acquire() as conn:
        await _set_rls_user(conn, user_id)
        rows = await conn.fetch(
            """SELECT id, title, mode, model_used, project_id, created_at, updated_at
               FROM chat_threads
               WHERE user_id=$1 AND archived_at IS NULL
               ORDER BY updated_at DESC LIMIT 50""",
            user_id,
        )
    return [dict(r) for r in rows]


@router.patch("/v1/threads/{thread_id}")
async def rename_thread(thread_id: str, body: ThreadPatch, request: Request):
    user_id = _user_id(request)
    pool = get_pool()
    async with pool.acquire() as conn:
        await _set_rls_user(conn, user_id)
        result = await conn.execute(
            "UPDATE chat_threads SET title=$1, updated_at=now() WHERE id=$2 AND user_id=$3",
            body.title[:80],
            UUID(thread_id),
            user_id,
        )
    if result == "UPDATE 0":
        raise HTTPException(404, "Thread not found")
    return {"ok": True}


@router.delete("/v1/threads/{thread_id}")
async def archive_thread(thread_id: str, request: Request):
    user_id = _user_id(request)
    pool = get_pool()
    async with pool.acquire() as conn:
        await _set_rls_user(conn, user_id)
        result = await conn.execute(
            "UPDATE chat_threads SET archived_at=now() WHERE id=$1 AND user_id=$2",
            UUID(thread_id),
            user_id,
        )
    if result == "UPDATE 0":
        raise HTTPException(404, "Thread not found")
    return {"ok": True}


@router.get("/v1/threads/{thread_id}/messages")
async def get_thread_messages(thread_id: str, request: Request):
    user_id = _user_id(request)
    pool = get_pool()
    async with pool.acquire() as conn:
        await _set_rls_user(conn, user_id)
        rows = await conn.fetch(
            """SELECT id, role, content, model_used, council_detail,
                      memory_injected, latency_ms, created_at
               FROM chat_messages
               WHERE thread_id=$1
               ORDER BY created_at ASC""",
            UUID(thread_id),
        )
    return [dict(r) for r in rows]


@router.post("/v1/threads/{thread_id}/escalate")
async def escalate_to_overnight(
    thread_id: str, body: EscalateRequest, request: Request
):
    user_id = _user_id(request)
    pool = get_pool()
    created_by_uuid = uuid5(NAMESPACE_DNS, user_id)
    graph_id = uuid4()
    async with pool.acquire() as conn:
        await _set_rls_user(conn, user_id)
        thread = await conn.fetchrow(
            "SELECT title FROM chat_threads WHERE id=$1 AND user_id=$2",
            UUID(thread_id),
            user_id,
        )
        if not thread:
            raise HTTPException(404, "Thread not found")

        messages = await conn.fetch(
            "SELECT role, content FROM chat_messages WHERE thread_id=$1 ORDER BY created_at ASC",
            UUID(thread_id),
        )
        context_summary = "\n".join(
            f"{r['role']}: {r['content'][:300]}" for r in messages[-10:]
        )

        await conn.execute(
            """INSERT INTO alpha_task_graphs
               (id, title, status, created_by, metadata)
               VALUES ($1, $2, 'pending', $3, $4::jsonb)""",
            graph_id,
            f"Overnight: {thread['title']}",
            created_by_uuid,
            json.dumps(
                {
                    "source": "chat_escalation",
                    "thread_id": thread_id,
                    "reason": body.reason,
                    "context_summary": context_summary,
                }
            ),
        )
        await conn.execute(
            "UPDATE chat_threads SET mode='overnight', updated_at=now() WHERE id=$1",
            UUID(thread_id),
        )

    return {"ok": True, "task_graph_id": str(graph_id)}
