# PATTERNS — Step 6.5 Stage 1 Contract

This document locks the canonical RLS and background-writer patterns before Stages 2-5 begin migration work.

## 1. GUC Convention — Canonical: rls.*

Canonical convention for all new code and policies is `rls.*`.

Canonical GUC names:

- `rls.user_id` — TEXT, required for all user-scoped queries
- `rls.workspace_id` — TEXT, from JWT workspace claim
- `rls.role` — TEXT, role name from JWT
- `rls.vault_tier` — TEXT, classification tier (`00_PUBLIC` through `50_SECRETS`)
- `rls.is_admin` — BOOLEAN, admin flag
- `rls.is_kids` — BOOLEAN, child profile flag
- `rls.agent` — TEXT, background agent name when inside `SECURITY DEFINER`
- `rls.node` — TEXT, node name for agent heartbeats

Reference: `brain/db/rls.py` `rls_connection()` is the single source of truth for setting GUCs on a request path.

## 2. Strangler Migration Plan

Current state: three conventions live in parallel.

### `jarvis.*` policies (11)

- `alpha_conversation_memory.alpha_memory_isolation`
- `alpha_semantic_memory.semantic_isolation`
- `alpha_task_graphs.task_graph_isolation`
- `alpha_task_steps.task_step_isolation`
- `alpha_task_events.task_events_read`
- `alpha_memory_isolation` (policy reference in discovery policy inventory)
- `semantic_isolation` (`jarvis.current_user`, `jarvis.is_admin`)
- `task_graphs_isolation` (`jarvis.current_user`, `jarvis.role`)
- `task_steps_isolation` (`jarvis.current_user`, `jarvis.role`)
- `task_events_isolation` (`jarvis.current_user`)
- `buddy_events_isolation` (`jarvis.current_user`, `jarvis.role`) [from migration definition]

### `app.*` policies (10)

- `alpha_conversation_memory.child_memory_rating`
- `alpha_conversation_memory.child_memory_write`
- `alpha_task_graphs.child_task_isolation`
- `chat_threads.child_thread_isolation`
- `chat_messages.child_content_rating`
- `chat_messages.child_message_isolation`
- `vault_documents.vault_documents_read`
- `vault_documents.vault_documents_write`
- `vault_pipeline.vault_pipeline_admin`
- `vault_access_log.vault_access_log_admin`

### `rls.*` policies (3)

- `chat_threads.chat_threads_isolation`
- `chat_messages.chat_messages_isolation`
- `alpha_watchdog_events.watchdog_events_system_write`

Deprecation path:

1. Phase A (now): `rls_connection()` triple-sets all three. New code uses `rls.*` only.
2. Phase B (per-table): rewrite each policy to check canonical `rls.*` name. Keep `jarvis.*` / `app.*` as fallback in `coalesce()` during transition.
3. Phase C: once every policy is migrated, WARN log on `jarvis.*` / `app.*` access for one week.
4. Phase D: final migration drops `jarvis.*` / `app.*` from `rls_connection()` and all `coalesce()` fallbacks.

Migration state tracker:

| table_name | old_convention | new_convention | status |
|---|---|---|---|
| alpha_conversation_memory | jarvis.* + app.* | rls.* | not_started |
| alpha_semantic_memory | jarvis.* | rls.* | not_started |
| alpha_task_graphs | jarvis.* + app.* | rls.* | not_started |
| alpha_task_steps | jarvis.* | rls.* | not_started |
| alpha_task_events | jarvis.* | rls.* | not_started |
| alpha_buddy_events | jarvis.* (migration intent) | rls.* | not_started |
| chat_threads | app.* + rls.* | rls.* | in_progress |
| chat_messages | app.* + rls.* | rls.* | in_progress |
| vault_documents | app.* | rls.* | not_started |
| vault_pipeline | app.* | rls.* | not_started |
| vault_access_log | app.* | rls.* | not_started |
| alpha_watchdog_events | rls.* | rls.* | canonical_only |

Allowed status values: `not_started` | `in_progress` | `canonical_only` | `cleanup_pending`.

## 3. SECURITY DEFINER Pattern for Background Agents

Every background agent writer (`Buddy`, `executor`, `watchdog`, `approval_notifier`) MUST call a `SECURITY DEFINER` function. No raw `INSERT` against RLS-enforced tables.

Function requirements:

- Owned by `jarvisbrain` (superuser)
- `search_path = pg_catalog, public, pg_temp` (CVE-2018-1058 mitigation)
- Schema-qualified references inside the function body
- Re-raise constraint violations (SQLSTATE 23xxx)
- `WARNING + RETURN FALSE` on other errors (`SQLSTATE 08xxx`, `40001` retryable classes get asyncpg retry)
- Set `rls.agent` and `rls.node` at function entry so policies can audit caller identity

Template:

```sql
CREATE OR REPLACE FUNCTION record_<event>(...)
RETURNS <type>
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
  PERFORM set_config('rls.agent', <agent_name>, true);
  PERFORM set_config('rls.node', <node>, true);
  INSERT INTO <table> (...) VALUES (...);
  RETURN ...;
EXCEPTION
  WHEN sqlstate '23503' OR sqlstate '23505' OR sqlstate '23514' THEN
    RAISE;
  WHEN OTHERS THEN
    RAISE WARNING 'record_<event> failed: % (SQLSTATE=%)', SQLERRM, SQLSTATE;
    RETURN NULL;
END;
$$;
```

## 4. System Sentinel User Convention

For events not tied to a real user (`approval notifications`, `watchdog events`, `buddy lifecycle events`), use sentinel `user_id = 'system'` (`NOT NULL`).

Rationale:

- `NULL` handling in RLS policies is error-prone (`IS NULL` vs `=` comparisons)
- `alpha_watchdog_events` already uses this convention
- Sentinel value is greppable, searchable, indexable
- Policies can easily grant system-row visibility to admins only

Migration note: existing `NULL user_id` rows get updated to `'system'` in the same transaction as the policy change. Data migration happens inside the `CREATE POLICY` transaction to avoid a window of rejected rows.

## 5. Writer Pool Inventory

From discovery report section 6.

| Pool | File | Current GUC convention | Planned canonical | SECURITY DEFINER wrapped? |
|---|---|---|---|---|
| FastAPI app (rls_connection) | brain/db/rls.py | triple-set (`app.*`, `jarvis.*`, `rls.user_id`) | rls.* | N/A — request path |
| Executor | brain/tasks/executor.py | `jarvis.current_user`, `jarvis.role` | rls.* | Stage 3 |
| Buddy agent | brain/agents/buddy_agent.py | mostly none; one path sets `jarvis.current_user` only | rls.* via function | Stage 3 |
| Watchdog agent | brain/agents/watchdog_agent.py | `rls.user_id` only | rls.* via function | Stage 3 |
| Approval notifier | brain/services/approval_notifier.py | none | rls.* via function | Stage 3 |

## 6. Forward Pointer

This document is the contract for Stages 2-5 of Step 6.5. Any deviation requires updating this doc in the same commit.
