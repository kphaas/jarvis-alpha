"""Helpers for governed AgentFS artifact persistence."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import asyncpg

from brain.db.rls import platform_admin_connection
from brain.services.agent_workspace import WorkspacePathError, get_workspace_backend


async def persist_workspace_json_artifact(
    pool: asyncpg.Pool,
    run_id: UUID,
    *,
    audit_actor: str,
    relative_path: str,
    kind: str,
    document: dict[str, Any],
) -> dict[str, Any]:
    backend = get_workspace_backend()
    async with platform_admin_connection(
        source="buddy",
        audit_actor=audit_actor,
        pool=pool,
    ) as conn:
        row = await conn.fetchrow(
            """
            SELECT id, agent_id, created_at, workspace_backend, workspace_root,
                   policy_labels, approval_scope, retention_class
            FROM public.alpha_agent_runs
            WHERE id = $1
            """,
            run_id,
        )
        if not row:
            raise RuntimeError(f"agent run not found: {run_id}")

        try:
            manifest = backend.init_workspace(
                row["id"],
                row["agent_id"],
                _jsonb_list(row["policy_labels"]),
                row["approval_scope"],
                row["retention_class"],
                workspace_root=str(row["workspace_root"] or "").strip() or None,
                created_at=row["created_at"],
            )
        except WorkspacePathError as exc:
            raise RuntimeError(str(exc)) from exc

        if (
            row["workspace_root"] != manifest.workspace_root
            or row["workspace_backend"] != manifest.workspace_backend
        ):
            await conn.execute(
                """
                UPDATE public.alpha_agent_runs
                SET workspace_backend = $2,
                    workspace_root = $3
                WHERE id = $1
                """,
                row["id"],
                manifest.workspace_backend,
                manifest.workspace_root,
            )

        staged = backend.stage_text(
            run_id,
            relative_path,
            json.dumps(document, indent=2, sort_keys=True) + "\n",
            kind,
            content_type="application/json",
            policy_labels=_jsonb_list(row["policy_labels"]),
            workspace_root=manifest.workspace_root,
        )
        try:
            await conn.execute(
                """
                INSERT INTO public.alpha_agent_run_artifacts
                    (id, run_id, agent_id, relative_path, kind, content_type, size_bytes,
                     sha256, policy_labels)
                VALUES
                    ($1::uuid, $2::uuid, $3, $4, $5, $6, $7, $8, $9::jsonb)
                """,
                staged.record.artifact_id,
                staged.record.run_id,
                row["agent_id"],
                staged.record.relative_path,
                staged.record.kind,
                staged.record.content_type,
                staged.record.size_bytes,
                staged.record.sha256,
                json.dumps(list(staged.record.policy_labels)),
            )
            record = backend.commit_staged_artifact(staged)
        except Exception:
            await conn.execute(
                "DELETE FROM public.alpha_agent_run_artifacts WHERE id = $1::uuid",
                staged.record.artifact_id,
            )
            backend.cleanup_staged_artifact(staged)
            raise

    return record.to_dict()


def _jsonb_list(value: object) -> list[str]:
    if value is None:
        return []
    parsed = json.loads(value) if isinstance(value, str) else value
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]
