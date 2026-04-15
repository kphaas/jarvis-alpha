# TD-60 Legacy Child RLS Policies — Cleanup

**Date:** 2026-04-14
**Trigger:** Stage child profile RLS (session 2026-04-14 #04) discovered 8 pre-existing child policies using stale GUCs or redundant logic. All are PERMISSIVE — no functional impact today. Cleanup deferred.

---

## Summary

8 legacy PERMISSIVE child policies exist across 5 tables. None block access. Two use the stale `app.profile_role` GUC (no longer set by `rls.py`). Three reference `rating_level()` instead of the canonical `rating_allowed()`. Three are fully redundant with newer policies added this session.

---

## Policies To Drop

| Table | Policy | Issue |
|---|---|---|
| `alpha_conversation_memory` | `child_memory_rating` | Uses stale `app.profile_role` GUC + `rating_level()` — superseded by `child_content_filter` |
| `alpha_conversation_memory` | `child_memory_write` | PERMISSIVE INSERT with NULL qual — purpose unknown, no corresponding RESTRICTIVE |
| `alpha_dream_sessions` | `child_dream_isolation` | Requires `platform_admin` — children always locked out; `child_profile_scope` RESTRICTIVE handles this correctly |
| `alpha_dream_steps` | `child_dream_step_isolation` | Requires `platform_admin` — same issue as above |
| `alpha_task_graphs` | `child_task_isolation` | Requires `platform_admin` — redundant; `task_graph_isolation` PERMISSIVE already passes for children |
| `chat_messages` | `child_content_rating` | SELECT only + uses `rating_level()` — superseded by `child_messages_scope` RESTRICTIVE |
| `chat_messages` | `child_message_isolation` | PERMISSIVE ALL — overlaps with `child_messages_scope` RESTRICTIVE; creates confusion |
| `chat_threads` | `child_thread_isolation` | PERMISSIVE ALL — overlaps with `child_profile_scope` RESTRICTIVE |

---

## Risk Assessment

**Current risk: NONE** — all 8 are PERMISSIVE. They cannot block access. The RESTRICTIVE policies added in session 2026-04-14 #04 are the enforcement layer.

**Future risk if left:** Confusion during policy audits. `app.profile_role` GUC is no longer set — if any future code accidentally relies on `child_memory_rating`, it will silently pass for all users (GUC returns empty string, which never equals `'admin'`).

---

## Cleanup Migration

One migration — drop all 8 in a single transaction:

```sql
-- Migration: YYYYMMDD_HHMMSS_drop_legacy_child_policies.sql
BEGIN;
DROP POLICY IF EXISTS child_memory_rating        ON alpha_conversation_memory;
DROP POLICY IF EXISTS child_memory_write         ON alpha_conversation_memory;
DROP POLICY IF EXISTS child_dream_isolation      ON alpha_dream_sessions;
DROP POLICY IF EXISTS child_dream_step_isolation ON alpha_dream_steps;
DROP POLICY IF EXISTS child_task_isolation       ON alpha_task_graphs;
DROP POLICY IF EXISTS child_content_rating       ON chat_messages;
DROP POLICY IF EXISTS child_message_isolation    ON chat_messages;
DROP POLICY IF EXISTS child_thread_isolation     ON chat_threads;
COMMIT;
```

**Pre-condition:** Verify `child_profile_scope` and `child_messages_scope` RESTRICTIVE policies are live on all affected tables before running. Run `SELECT tablename, policyname, permissive FROM pg_policies WHERE policyname LIKE 'child%' ORDER BY tablename;` to confirm.

---

## Priority

**P3** — no functional impact today. Schedule with next TD cleanup pass.
