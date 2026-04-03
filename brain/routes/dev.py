"""
Dev Agent routes: GitHub issue analysis and grouped build-plan approval.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Literal
from uuid import NAMESPACE_DNS, uuid4, uuid5

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from brain.config.secrets import get_secret
from brain.db.pool import get_pool
from brain.middleware.jwt_auth import require_auth

dev_router = APIRouter(prefix="/v1/dev", tags=["dev"])

OLLAMA_BASE = "http://127.0.0.1:11434"
OLLAMA_MODEL = "llama3.1:8b"

_SYSTEM_GROUPER = (
    "You are a technical project manager. Group the provided GitHub issues by root "
    "cause or shared fix area. For each group, write a one-sentence task description "
    "and list the issue numbers. Return JSON only: "
    '{ "groups": [ { "task": str, "issues": [int], "category": str, '
    '"estimated_hours": int } ] }'
)


class AnalyzeBody(BaseModel):
    project_id: int = Field(..., ge=1)


class ApproveBody(BaseModel):
    project_id: int = Field(..., ge=1)
    group_index: int = Field(..., ge=0)
    build_mode: Literal["cursor", "claude_code"]
    template_category: str


def _user_id(request: Request) -> str:
    return getattr(request.state, "user_id", "anon")


async def _rls_dev(conn, request: Request) -> None:
    user_id = _user_id(request)
    role = getattr(request.state, "role", "user")
    await conn.execute(
        "SELECT set_config('jarvis.current_user', $1, true)",
        user_id,
    )
    await conn.execute(
        "SELECT set_config('jarvis.role', $1, true)",
        role,
    )


def _parse_owner_repo(repo_slug: str) -> tuple[str, str]:
    parts = [p for p in repo_slug.strip().split("/") if p]
    if len(parts) != 2:
        raise HTTPException(
            status_code=500,
            detail="alpha_projects.repo_slug must be owner/repo",
        )
    return parts[0], parts[1]


def _template_to_branch_type(template_category: str) -> str:
    m = {
        "bug_fix": "fix",
        "new_feature": "feat",
        "refactor": "refactor",
        "security": "sec",
        "ui_polish": "ui",
    }
    return m.get(template_category.strip(), "feat")


def _branch_slug(group_index: int, template_category: str) -> str:
    t = _template_to_branch_type(template_category)
    raw = f"group-{group_index}-{t}"
    return raw[:48]


def _build_branch_name(
    build_mode: str, group_index: int, template_category: str
) -> str:
    prefix = "forge" if build_mode == "cursor" else "claude"
    typ = _template_to_branch_type(template_category)
    slug = _branch_slug(group_index, template_category)
    return f"{prefix}/{typ}/{slug}"


def _strip_json_fence(text: str) -> str:
    s = text.strip()
    m = re.match(r"^```(?:json)?\s*([\s\S]*?)\s*```$", s)
    if m:
        return m.group(1).strip()
    return s


async def _github_open_issues(owner: str, repo: str, token: str) -> list[dict]:
    url = f"https://api.github.com/repos/{owner}/{repo}/issues"
    params = {"state": "open", "labels": "bug", "per_page": "100"}
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "jarvis-alpha-dev-agent",
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.get(url, params=params, headers=headers)
    if r.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"GitHub API error: HTTP {r.status_code}",
        )
    data = r.json()
    if not isinstance(data, list):
        raise HTTPException(status_code=502, detail="GitHub API returned invalid JSON")
    out: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        if "pull_request" in item:
            continue
        out.append(item)
    return out


async def _ollama_group_issues(issues: list[dict]) -> list[dict]:
    compact = [
        {
            "number": it.get("number"),
            "title": it.get("title"),
            "body": (it.get("body") or "")[:800],
        }
        for it in issues
        if isinstance(it.get("number"), int)
    ]
    user_prompt = json.dumps({"issues": compact}, indent=2)
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_GROUPER},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.post(f"{OLLAMA_BASE}/api/chat", json=payload)
    if r.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Ollama error: HTTP {r.status_code}",
        )
    body = r.json()
    msg = (body.get("message") or {}) if isinstance(body, dict) else {}
    content = msg.get("content") if isinstance(msg, dict) else None
    if not isinstance(content, str) or not content.strip():
        return []
    try:
        parsed = json.loads(_strip_json_fence(content))
    except json.JSONDecodeError:
        return []
    groups = parsed.get("groups") if isinstance(parsed, dict) else None
    if not isinstance(groups, list):
        return []
    normalized: list[dict] = []
    for g in groups:
        if not isinstance(g, dict):
            continue
        task = g.get("task")
        issues_raw = g.get("issues")
        cat = g.get("category")
        est = g.get("estimated_hours")
        if not isinstance(task, str):
            continue
        nums: list[int] = []
        if isinstance(issues_raw, list):
            for n in issues_raw:
                if isinstance(n, int):
                    nums.append(n)
                elif isinstance(n, str) and n.isdigit():
                    nums.append(int(n))
        normalized.append(
            {
                "task": task,
                "issues": nums,
                "category": cat if isinstance(cat, str) else "general",
                "estimated_hours": int(est) if isinstance(est, int) else 0,
            }
        )
    return normalized


@dev_router.post("/analyze")
async def dev_analyze(
    body: AnalyzeBody,
    request: Request,
    _: str = Depends(require_auth),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        await _rls_dev(conn, request)
        row = await conn.fetchrow(
            "SELECT repo_slug FROM alpha_projects WHERE id = $1",
            body.project_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="project not found")
    repo_slug = row["repo_slug"]
    if not repo_slug or not str(repo_slug).strip():
        raise HTTPException(status_code=500, detail="project has no repo_slug")

    try:
        token = get_secret("GITHUB_TOKEN")
    except KeyError:
        raise HTTPException(status_code=500, detail="GITHUB_TOKEN not configured")

    owner, repo = _parse_owner_repo(str(repo_slug))
    issues = await _github_open_issues(owner, repo, token)
    groups = await _ollama_group_issues(issues) if issues else []

    generated_at = datetime.now(timezone.utc).isoformat()
    return {
        "plan": groups,
        "repo": str(repo_slug),
        "issue_count": len(issues),
        "generated_at": generated_at,
    }


@dev_router.post("/approve")
async def dev_approve(
    body: ApproveBody,
    request: Request,
    _: str = Depends(require_auth),
):
    user_id = _user_id(request)
    created_by = uuid5(NAMESPACE_DNS, user_id)
    graph_id = uuid4()

    metadata: dict = {
        "build_mode": body.build_mode,
        "template_category": body.template_category,
        "group_index": body.group_index,
        "project_id": body.project_id,
    }
    cursor_prompt: str | None
    if body.build_mode == "cursor":
        cursor_prompt = "Cursor prompt will be generated by forge runner"
        status_note = None
    else:
        cursor_prompt = None
        status_note = "headless_not_available — Claude Code not installed on Sandbox"
        metadata["status_note"] = status_note

    title = (
        f"Dev build — project {body.project_id} "
        f"group {body.group_index} ({body.build_mode})"
    )

    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            role = getattr(request.state, "role", "user")
            await conn.execute(
                "SELECT set_config('jarvis.current_user', $1, true)",
                str(created_by),
            )
            await conn.execute(
                "SELECT set_config('jarvis.role', $1, true)",
                role,
            )
            await conn.execute(
                """
                INSERT INTO alpha_task_graphs (
                    id, title, status, created_by, metadata
                )
                VALUES ($1, $2, 'approved', $3, $4::jsonb)
                """,
                graph_id,
                title,
                created_by,
                json.dumps(metadata),
            )

    branch_name = _build_branch_name(
        body.build_mode, body.group_index, body.template_category
    )

    return {
        "task_graph_id": graph_id,
        "branch_name": branch_name,
        "cursor_prompt": cursor_prompt,
    }
