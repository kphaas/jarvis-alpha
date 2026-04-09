# TD-44 — Agent Pool Cutover Phase 2 (Watchdog + Tasks)

**Status:** stub — opened during Stage 5c.
**Filed:** 2026-04-09
**Owner:** unassigned (Ken to triage)

## Background

Stage 5c flipped `brain/agents/buddy_agent.py` from the read-only `ALPHA_DB_DSN`
(`jarvis_alpha_app`) to `ALPHA_DB_DSN_BUDDY` (`jarvis_alpha_writer`) and wrapped its
remaining naked reads in SECURITY DEFINER functions. The Stage 5 discovery
(`docs/STAGE5_DISCOVERY.md`, Task 5) identified four other background pools that
still consume the read-only DSN and have not been audited for FORCE RLS
compatibility.

## In scope

| File | Pool | Current DSN env var |
|------|------|---------------------|
| `brain/agents/watchdog_agent.py` (~L359) | watchdog background loop | `ALPHA_DB_DSN` |
| `brain/tasks/executor.py` (~L406) | task executor daemon | `JARVIS_ALPHA_DB_DSN` |
| `brain/tasks/watchdog.py` (~L149) | task watchdog daemon | `JARVIS_ALPHA_DB_DSN` |

These pools write to `alpha_watchdog_events`, `alpha_task_graphs`,
`alpha_task_steps`, `alpha_task_events` — none of which currently have FORCE RLS
enforced, which is why they were left out of Stage 5b/5c.

## What this TD captures

1. The four pools above need the same Stage 5c treatment (per-service writer
   DSN env var, SECDEF wrappers for any naked reads against tables that may
   later get FORCE RLS, dead-GUC removal).
2. The decision of whether each task table should also move to FORCE RLS is
   open and should be made before Phase 2 implementation starts.
3. `_expire_pending_approvals` in `buddy_agent.py` writes
   `alpha_approval_queue` and `alpha_approval_audit` with bare DML. Those
   tables are out of Stage 5c scope but should be wrapped in SECDEF when
   FORCE RLS is enabled on them. See the inline `# TD:` comment near
   `_expire_pending_approvals` and the Stage 5c handoff notes.

## Next action

Ken to schedule a Stage 5d planning pass: discovery doc → design doc → branch.
Until then, this file exists only to ensure the work is not forgotten.
