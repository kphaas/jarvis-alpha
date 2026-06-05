#!/usr/bin/env python3
"""Run rollback-only canaries for Alpha SECURITY DEFINER owner transfer."""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.postgres_owner_inventory import (  # noqa: E402
    DEFAULT_PSQL_BIN,
    CommandResult,
    parse_rows,
    run_psql,
)

DEFAULT_OWNER_ROLE = "jarvis_alpha_owner"
CANARY_AGENT_ID = "phase3b_canary_agent"
CANARY_PROFILE_ID = "phase3b_canary_profile"


@dataclass(frozen=True)
class SecdefFunction:
    identity: str
    owner: str
    language: str


@dataclass(frozen=True)
class CanarySpec:
    identity: str
    canary_sql: str
    setup_sql: str = ""
    skip_reason: str = ""
    note: str = ""


@dataclass(frozen=True)
class CanaryResult:
    identity: str
    status: str
    owner_before: str
    language: str
    detail: str
    note: str


@dataclass(frozen=True)
class CanaryReport:
    database: str
    source: str
    target_owner: str
    generated_by: str
    results: list[CanaryResult]
    summary: dict[str, int]


COMMON_AGENT_SETUP = f"""
INSERT INTO public.alpha_agents (
    agent_id,
    display_name,
    purpose,
    risk_tier,
    status,
    enabled,
    owner,
    metadata
)
VALUES (
    '{CANARY_AGENT_ID}',
    'Phase3B Canary',
    'Rollback-only SECURITY DEFINER owner canary',
    'T1',
    'active',
    true,
    'security',
    '{{}}'::jsonb
)
ON CONFLICT (agent_id) DO UPDATE SET
    status = 'active',
    enabled = true,
    metadata = '{{}}'::jsonb,
    updated_at = NOW();
""".strip()


def _specs() -> dict[str, CanarySpec]:
    specs = [
        CanarySpec(
            "public.bump_memory_access(p_ids uuid[])",
            "SELECT public.bump_memory_access(ARRAY[]::uuid[]);",
        ),
        CanarySpec(
            "public.cap_episodic_memory(p_user_id text, p_max_rows integer)",
            "SELECT public.cap_episodic_memory('phase3b_canary_user', 1000);",
        ),
        CanarySpec(
            "public.cap_semantic_memory(p_user_id text, p_max_rows integer)",
            "SELECT public.cap_semantic_memory('phase3b_canary_user', 200);",
        ),
        CanarySpec(
            "public.claim_agent_due_run(p_agent_id text, p_interval_seconds integer)",
            f"SELECT public.claim_agent_due_run('{CANARY_AGENT_ID}', 60);",
            setup_sql=COMMON_AGENT_SETUP,
        ),
        CanarySpec(
            "public.consume_approved_queue_item(p_queue_id uuid)",
            "SELECT public.consume_approved_queue_item(gen_random_uuid());",
        ),
        CanarySpec(
            "public.decide_approval("
            "p_queue_id uuid, p_decision text, p_decided_by text, p_nonce text"
            ")",
            """
WITH queued AS (
    SELECT public.enqueue_approval_request(
        ARRAY['phase3b.canary'],
        'T1',
        'phase3b_decide',
        'service',
        'Phase3B decide canary',
        'phase3b-decide-hash-__NONCE__',
        'phase3b-decide-request-__NONCE__'
    ) AS id
)
SELECT count(*)
FROM public.decide_approval(
    (SELECT id FROM queued),
    'approved',
    'phase3b',
    'phase3b-decide-decision-__NONCE__'
);
""".strip(),
        ),
        CanarySpec(
            "public.enqueue_approval_request("
            "p_action_classes text[], p_risk_tier text, p_actor_sub text, "
            "p_actor_type text, p_description text, p_parameters_hash text, "
            "p_nonce text"
            ")",
            """
SELECT public.enqueue_approval_request(
    ARRAY['phase3b.canary'],
    'T1',
    'phase3b_enqueue',
    'service',
    'Phase3B enqueue canary',
    'phase3b-enqueue-hash-__NONCE__',
    'phase3b-enqueue-nonce-__NONCE__'
);
""".strip(),
        ),
        CanarySpec(
            "public.enqueue_dream_step_approval_request("
            "p_action_classes text[], p_risk_tier text, p_actor_sub text, "
            "p_actor_type text, p_description text, p_parameters_hash text, "
            "p_parameters_preview text, p_nonce text"
            ")",
            """
SELECT public.enqueue_dream_step_approval_request(
    ARRAY['phase3b.canary'],
    'T1',
    'phase3b_dream',
    'service',
    'Phase3B dream approval canary',
    'phase3b-dream-hash-__NONCE__',
    'preview',
    'phase3b-dream-nonce-__NONCE__'
);
""".strip(),
        ),
        CanarySpec(
            "public.evict_episodic_memory_older_than(p_user_id text, p_days integer)",
            "SELECT public.evict_episodic_memory_older_than('phase3b_canary_user', 30);",
        ),
        CanarySpec(
            "public.evict_expired_working_memory()",
            "SELECT public.evict_expired_working_memory();",
        ),
        CanarySpec(
            "public.expire_orphan_approved_rows()",
            "SELECT public.expire_orphan_approved_rows();",
        ),
        CanarySpec(
            "public.expire_pending_approvals()",
            "SELECT public.expire_pending_approvals();",
        ),
        CanarySpec(
            "public.finish_agent_run("
            "p_run_id uuid, p_status text, p_cost_usd numeric, "
            "p_error_text text, p_metadata jsonb"
            ")",
            """
WITH run_row AS (
    INSERT INTO public.alpha_agent_runs (
        agent_id,
        status,
        trigger_type,
        started_at,
        metadata
    )
    VALUES (
        'phase3b_canary_agent',
        'running',
        'manual',
        NOW(),
        '{}'::jsonb
    )
    RETURNING id
)
SELECT public.finish_agent_run(
    (SELECT id FROM run_row),
    'succeeded',
    0,
    NULL,
    '{"phase3b_canary": true}'::jsonb
);
""".strip(),
            setup_sql=COMMON_AGENT_SETUP,
        ),
        CanarySpec(
            "public.forget_memory_by_topic(p_user_id text, p_topic text)",
            "SELECT public.forget_memory_by_topic('phase3b_canary_user', 'canary');",
        ),
        CanarySpec(
            "public.forget_working_memory(p_user_id text)",
            "SELECT public.forget_working_memory('phase3b_canary_user');",
        ),
        CanarySpec(
            "public.get_buddy_promotion_candidates(p_user_id text)",
            "SELECT count(*) FROM public.get_buddy_promotion_candidates('phase3b_canary_user');",
        ),
        CanarySpec(
            "public.list_active_memory_users()",
            "SELECT cardinality(public.list_active_memory_users());",
        ),
        CanarySpec(
            "public.mark_agent_event_notification("
            "p_event_id uuid, p_status text, p_result jsonb, p_error text"
            ")",
            """
WITH event_row AS (
    INSERT INTO public.alpha_agent_events (
        agent_id,
        event_type,
        severity,
        title,
        message,
        notification_status
    )
    VALUES (
        'phase3b_canary_agent',
        'canary',
        'info',
        'Phase3B canary',
        'Rollback-only canary',
        'pending'
    )
    RETURNING id
)
SELECT public.mark_agent_event_notification(
    (SELECT id FROM event_row),
    'sent',
    '{"phase3b_canary": true}'::jsonb,
    NULL
);
""".strip(),
            setup_sql=COMMON_AGENT_SETUP,
        ),
        CanarySpec(
            "public.pgaudit_ddl_command_end()",
            "",
            skip_reason="extension_event_trigger",
            note="pgaudit C event trigger ownership is held outside Phase 3B canaries.",
        ),
        CanarySpec(
            "public.pgaudit_sql_drop()",
            "",
            skip_reason="extension_event_trigger",
            note="pgaudit C event trigger ownership is held outside Phase 3B canaries.",
        ),
        CanarySpec(
            "public.record_agent_event("
            "p_agent_id text, p_event_type text, p_title text, p_message text, "
            "p_severity text, p_payload jsonb, p_run_id uuid, "
            "p_correlation_id text, p_channel_key text, "
            "p_notification_status text"
            ")",
            """
SELECT public.record_agent_event(
    'phase3b_canary_agent',
    'canary',
    'Phase3B canary',
    'Rollback-only canary',
    'info',
    '{"phase3b_canary": true}'::jsonb,
    NULL,
    'phase3b-__NONCE__',
    'alpha_events',
    'not_requested'
);
""".strip(),
            setup_sql=COMMON_AGENT_SETUP,
        ),
        CanarySpec(
            "public.record_buddy_event("
            "p_user_id text, p_event_type text, p_title text, p_body text, "
            "p_priority integer, p_source text, p_payload jsonb"
            ")",
            """
SELECT public.record_buddy_event(
    'phase3b_canary_user',
    'system',
    'Phase3B canary',
    'Rollback-only canary',
    2,
    'phase3b',
    '{"phase3b_canary": true}'::jsonb
);
""".strip(),
        ),
        CanarySpec(
            "public.record_secret_access("
            "p_key_name text, p_source text, "
            "p_accessed_at timestamp with time zone, p_node text"
            ")",
            """
SELECT public.record_secret_access(
    'PHASE3B_CANARY_KEY',
    'phase3b_canary',
    NOW(),
    'brain'
);
""".strip(),
        ),
        CanarySpec(
            "public.record_watchdog_event("
            "p_service_name text, p_node text, p_event_type text, "
            "p_previous_state text, p_current_state text, "
            "p_consecutive_failures integer, p_latency_ms numeric, "
            "p_http_status integer, p_error_message text, "
            "p_action_taken text, p_trace_id uuid"
            ")",
            """
SELECT public.record_watchdog_event(
    'phase3b_canary',
    'brain',
    'check_error',
    'ok',
    'ok',
    0,
    0,
    200,
    NULL,
    NULL,
    gen_random_uuid()
);
""".strip(),
        ),
        CanarySpec(
            "public.run_buddy_memory_maintenance(p_user_id text)",
            "SELECT public.run_buddy_memory_maintenance('phase3b_canary_user');",
        ),
        CanarySpec(
            "public.save_semantic_memory(p_user_id uuid, p_fact text, p_category text)",
            """
SELECT public.save_semantic_memory(
    gen_random_uuid(),
    'phase3b canary fact __NONCE__',
    'preference'
);
""".strip(),
        ),
        CanarySpec(
            "public.start_agent_run("
            "p_agent_id text, p_trigger_type text, "
            "p_trace_id text, p_metadata jsonb"
            ")",
            """
SELECT public.start_agent_run(
    'phase3b_canary_agent',
    'manual',
    'phase3b-__NONCE__',
    '{"phase3b_canary": true}'::jsonb
);
""".strip(),
            setup_sql=COMMON_AGENT_SETUP,
        ),
        CanarySpec(
            "public.store_conversation_memory("
            "p_user_id text, p_session_id text, p_role text, p_summary text, "
            "p_embedding vector, p_tier text, p_persistent boolean, "
            "p_importance double precision"
            ")",
            """
SELECT public.store_conversation_memory(
    'phase3b_canary_user',
    'phase3b_session',
    'user',
    'Phase3B rollback-only memory canary',
    NULL::vector,
    'working',
    false,
    0.1
);
""".strip(),
        ),
        CanarySpec(
            "public.store_message_body_vault("
            "p_channel text, p_external_account text, "
            "p_external_message_id text, p_external_thread_id text, "
            "p_body_plaintext text, p_summary text, p_body_key text, "
            "p_retention_expires_at timestamp with time zone"
            ")",
            """
SELECT public.store_message_body_vault(
    'gmail',
    'phase3b',
    'phase3b-message-__NONCE__',
    'phase3b-thread',
    'Phase3B rollback-only body canary',
    'Phase3B canary summary',
    'phase3b-canary-key',
    NOW() + INTERVAL '1 day'
);
""".strip(),
        ),
        CanarySpec(
            "public.sync_profile_to_user()",
            f"""
INSERT INTO public.alpha_profiles (
    id,
    display_name,
    role,
    pin_hash,
    max_rating
)
VALUES (
    '{CANARY_PROFILE_ID}',
    'Phase3B Canary',
    'admin',
    'phase3b-canary-hash',
    'all_ages'
);
UPDATE public.alpha_profiles
SET display_name = 'Phase3B Canary Updated'
WHERE id = '{CANARY_PROFILE_ID}';
DELETE FROM public.alpha_profiles
WHERE id = '{CANARY_PROFILE_ID}';
""".strip(),
            note="Trigger canary uses the same platform_admin RLS context as admin writes.",
        ),
        CanarySpec(
            "public.update_agent_runtime_metadata(p_agent_id text, p_metadata jsonb)",
            """
SELECT public.update_agent_runtime_metadata(
    'phase3b_canary_agent',
    '{"phase3b_canary": true}'::jsonb
);
""".strip(),
            setup_sql=COMMON_AGENT_SETUP,
        ),
        CanarySpec(
            "public.upsert_dream_agent_run(p_session_id bigint)",
            """
WITH dream_session AS (
    INSERT INTO public.alpha_dream_sessions (
        status,
        trigger,
        goal_type,
        goal_text
    )
    VALUES (
        'pending',
        'manual',
        'default',
        'Phase3B rollback-only dream canary'
    )
    RETURNING id
)
SELECT public.upsert_dream_agent_run((SELECT id FROM dream_session));
""".strip(),
            setup_sql=COMMON_AGENT_SETUP.replace(CANARY_AGENT_ID, "dream_mode"),
        ),
    ]
    return {spec.identity: spec for spec in specs}


def collect_secdef_functions(
    *,
    psql_bin: str,
    db: str,
    user: str,
    host: str,
    ssh_target: str | None,
) -> list[SecdefFunction]:
    query = """
SELECT format('%I.%I(%s)',
              n.nspname,
              p.proname,
              pg_get_function_identity_arguments(p.oid)),
       pg_get_userbyid(p.proowner),
       l.lanname
FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
JOIN pg_language l ON l.oid = p.prolang
WHERE p.prosecdef
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND n.nspname NOT LIKE 'pg_toast%'
ORDER BY n.nspname, p.proname, pg_get_function_identity_arguments(p.oid);
""".strip()
    result = run_psql(
        query,
        psql_bin=psql_bin,
        db=db,
        user=user,
        host=host,
        ssh_target=ssh_target,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"SECURITY DEFINER catalog query failed: "
            f"{(result.stderr or result.stdout).strip()}"
        )
    functions: list[SecdefFunction] = []
    for parsed in parse_rows(result.stdout):
        if len(parsed) < 3:
            continue
        functions.append(
            SecdefFunction(
                identity=parsed[0],
                owner=parsed[1],
                language=parsed[2],
            )
        )
    return functions


def render_canary_transaction(
    *,
    identity: str,
    target_owner: str,
    setup_sql: str,
    canary_sql: str,
    nonce: str,
) -> str:
    rendered_setup = _render_template(setup_sql, nonce)
    rendered_canary = _render_template(canary_sql, nonce)
    statements = [
        "BEGIN;",
        "SET LOCAL lock_timeout = '2s';",
        "SET LOCAL statement_timeout = '15s';",
        "SET LOCAL idle_in_transaction_session_timeout = '30s';",
        "SELECT set_config('rls.role', 'platform_admin', true);",
    ]
    if rendered_setup:
        statements.append(rendered_setup.rstrip(";") + ";")
    statements.append(f"ALTER FUNCTION {identity} OWNER TO {target_owner};")
    statements.append(rendered_canary.rstrip(";") + ";")
    statements.append("ROLLBACK;")
    return "\n".join(statements)


def _render_template(template: str, nonce: str) -> str:
    return template.replace("__NONCE__", nonce)


def run_canaries(args: argparse.Namespace) -> CanaryReport:
    functions = collect_secdef_functions(
        psql_bin=args.psql_bin,
        db=args.db,
        user=args.user,
        host=args.host,
        ssh_target=args.ssh_target,
    )
    specs = _specs()
    seen = {function.identity for function in functions}
    results: list[CanaryResult] = []
    for function in functions:
        spec = specs.get(function.identity)
        if spec is None:
            results.append(
                CanaryResult(
                    identity=function.identity,
                    status="uncovered",
                    owner_before=function.owner,
                    language=function.language,
                    detail="No canary spec exists for this SECURITY DEFINER function.",
                    note="Add a rollback-only canary before ownership transfer.",
                )
            )
            continue
        if spec.skip_reason:
            results.append(
                CanaryResult(
                    identity=function.identity,
                    status="skipped",
                    owner_before=function.owner,
                    language=function.language,
                    detail=spec.skip_reason,
                    note=spec.note,
                )
            )
            continue
        nonce = uuid.uuid4().hex
        query = render_canary_transaction(
            identity=function.identity,
            target_owner=args.target_owner,
            setup_sql=spec.setup_sql,
            canary_sql=spec.canary_sql,
            nonce=nonce,
        )
        result = run_psql(
            query,
            psql_bin=args.psql_bin,
            db=args.db,
            user=args.user,
            host=args.host,
            ssh_target=args.ssh_target,
            timeout=args.timeout,
        )
        results.append(_result_from_command(function, spec, result))

    for identity, spec in specs.items():
        if identity in seen:
            continue
        results.append(
            CanaryResult(
                identity=identity,
                status="missing",
                owner_before="",
                language="",
                detail="Canary spec did not match a live SECURITY DEFINER function.",
                note=spec.note,
            )
        )

    source = f"ssh:{args.ssh_target}" if args.ssh_target else f"local:{args.host}"
    return CanaryReport(
        database=args.db,
        source=source,
        target_owner=args.target_owner,
        generated_by="scripts/postgres_secdef_canary.py",
        results=results,
        summary=summarize(results),
    )


def _result_from_command(
    function: SecdefFunction,
    spec: CanarySpec,
    result: CommandResult,
) -> CanaryResult:
    if result.returncode == 0:
        return CanaryResult(
            identity=function.identity,
            status="pass",
            owner_before=function.owner,
            language=function.language,
            detail="Rollback-only owner-transfer canary passed.",
            note=spec.note,
        )
    detail = (result.stderr or result.stdout).strip().replace("\n", " ")
    return CanaryResult(
        identity=function.identity,
        status="fail",
        owner_before=function.owner,
        language=function.language,
        detail=detail[:500],
        note=spec.note,
    )


def summarize(results: list[CanaryResult]) -> dict[str, int]:
    summary: dict[str, int] = {"total": len(results)}
    for result in results:
        summary[result.status] = summary.get(result.status, 0) + 1
    return dict(sorted(summary.items()))


def render_json(report: CanaryReport) -> str:
    return json.dumps(asdict(report), indent=2, sort_keys=True) + "\n"


def render_markdown(report: CanaryReport) -> str:
    lines = [
        "# Alpha SECURITY DEFINER Phase 3B Canary Report",
        "",
        f"Generated by `{report.generated_by}`.",
        f"Catalog source: `{report.source}`.",
        f"Database: `{report.database}`.",
        f"Temporary target owner: `{report.target_owner}`.",
        "",
        "Each canary runs in its own transaction, temporarily changes one",
        "`SECURITY DEFINER` function owner, executes a synthetic call, and",
        "rolls the transaction back.",
        "",
        "## Summary",
        "",
        "| Status | Count |",
        "|---|---:|",
    ]
    for key, value in report.summary.items():
        lines.append(f"| `{key}` | {value} |")

    lines.extend(
        [
            "",
            "## Results",
            "",
            "| Function | Owner Before | Language | Status | Detail | Note |",
            "|---|---|---|---|---|---|",
        ]
    )
    for result in report.results:
        detail = result.detail.replace("|", "\\|")
        note = result.note.replace("|", "\\|")
        lines.append(
            f"| `{result.identity}` | `{result.owner_before}` | "
            f"`{result.language}` | `{result.status}` | {detail} | {note} |"
        )

    lines.extend(
        [
            "",
            "## Phase 3B Decision Gate",
            "",
            "- Continue only if all non-skipped functions are `pass`.",
            "- Treat `uncovered`, `missing`, or `fail` as blockers.",
            "- Keep pgaudit extension event triggers held unless an extension",
            "  ownership plan is separately reviewed.",
            "- This report does not demote `jarvisbrain`.",
            "",
        ]
    )
    return "\n".join(lines)


def has_blockers(report: CanaryReport) -> bool:
    return any(
        result.status in {"fail", "uncovered", "missing"} for result in report.results
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run rollback-only Alpha SECURITY DEFINER owner canaries"
    )
    parser.add_argument("--db", default=os.getenv("POSTGRES_OWNER_DB", "jarvis_alpha"))
    parser.add_argument(
        "--user", default=os.getenv("POSTGRES_OWNER_USER", "jarvisbrain")
    )
    parser.add_argument("--host", default=os.getenv("POSTGRES_OWNER_HOST", "localhost"))
    parser.add_argument("--psql-bin", default=os.getenv("PSQL_BIN", DEFAULT_PSQL_BIN))
    parser.add_argument(
        "--ssh-target",
        default=os.getenv("POSTGRES_OWNER_SSH_TARGET"),
        help="Optional SSH target for running canaries on Brain.",
    )
    parser.add_argument("--target-owner", default=DEFAULT_OWNER_ROLE)
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_canaries(args)
    rendered = render_json(report) if args.format == "json" else render_markdown(report)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 1 if has_blockers(report) else 0


if __name__ == "__main__":
    raise SystemExit(main())
