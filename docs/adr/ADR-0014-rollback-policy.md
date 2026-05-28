# ADR-0014: Rollback Policy — PR-Revert Only

**Status:** Accepted
**Date:** 2026-05-28
**Related:** ADR-0013 (Backup & Recovery Architecture), GAP_ANALYSIS_v2 AUDIT-7, `scripts/jarvisalpha_rollback.sh`

## Context

`jarvis-alpha` ships forward via `scripts/jarvisalpha_deploy.sh` — Sandbox-driven, PR-merged code fans out to Brain/Gateway/Endpoint over SSH. Until Session 2, there was no formalized reverse path — only advisory text in the deploy script's failure box ("PR a revert of <hash>, then re-run this script after merge").

AUDIT-7 identified the missing rollback script as a P1 gap. Phase 3a discovery surfaced two architectural constraints that shape the solution:

1. **Force-push to `main` is blocked at two layers:**
   - Pre-commit hook `JARVIS force-push block on protected refs` (local enforcement)
   - GitHub branch protection requires 6 CI checks + PR path (server enforcement)
2. **Native `gh pr revert <N>` exists** and produces a revert PR automatically via the gh CLI.

Together, these mean the **only** rollback path consistent with the existing security model is **PR-revert**. There is no infrastructure-sanctioned bypass for "emergency" direct-push rollback.

## Decision

`scripts/jarvisalpha_rollback.sh` implements **PR-revert as the only rollback path**. The script:

1. Accepts a merged PR number as its argument
2. Validates preflight (on Sandbox, on main, clean tree, fast-forward from origin)
3. Resolves the PR to its merge commit and verifies it's an ancestor of current HEAD
4. **Halts on DB migration detection** unless `--db-restored` flag asserts the operator manually restored DB state
5. **Halts on stale backups** (newest > 36h old) unless `--skip-backup-check` overrides
6. Operates in one of three modes:
   - `--dry-run` (default, plan-only)
   - `--open` (create revert PR, exit — operator merges manually)
   - `--full` (open + watch CI + merge + redeploy)
7. `--full` mode requires an explicit `--yes` flag — no implicit confirmation
8. Emits `##EVT##` events, `mm_notify`, and `buddy_event` for parity with `pg_backup_alpha.sh` and `jarvisalpha_deploy.sh`

### Explicitly out of scope

- **Automated database rollback.** Per-migration `_rollback.sql` files exist in `brain/db/migrations/` but they are manual DDL inverses, not a runner. The script HALTS when migrations are detected in the revert range; the operator must manually restore from a backup taken **before** the migration was applied, then re-run with `--db-restored`. The script cannot validate the operator's assertion.
- **Multi-PR atomic revert.** One PR per invocation. Multi-PR rollbacks require multiple sequential invocations.
- **Tag-based rollback.** Deploys are not tagged today. If tag discipline emerges, revisit.
- **Local-only emergency mode.** Force-push is blocked by design; bypassing the protections to enable a faster rollback would be a security regression.

### Rationale for no "emergency" mode

Earlier design candidate (hybrid: PR-revert + `--emergency` local-reset) was rejected after Phase 3a discovery. To make `--emergency` functional would require:

- Bypassing the pre-push hook (`--no-verify`) — local protection defeated
- Force-pushing to `main` (requires temporarily disabling branch protection) — server protection defeated
- Operating on each node's local repo without origin sync — guarantees re-deployment of the broken commit on next pull

The ~5-minute CI floor for a revert PR is acceptable for a personal/family AI system. If multi-tenant or commercial use emerges, revisit (e.g. dedicated `hotfix` branch with relaxed protection).

## Consequences

### Positive

- **Audit trail:** every rollback is a merged PR, fully traceable in GitHub history
- **Same gates as forward deploys:** branch protection and CI apply to rollbacks, preventing rollback-from-broken-state
- **Single rollback script, no bypass flag:** removes the temptation to misuse an "emergency" mode in a panic
- **Symmetric with forward deploy:** same eventing, notification channels, preflight discipline — operators learn one pattern

### Negative

- **Minimum rollback wall-clock = CI duration** (typically 3–6 minutes)
- **DB migrations require operator judgment** and manual backup restore; script cannot automate this safely
- **No code-rollback path if GitHub or CI is unreachable;** documented as accepted residual risk

### Future considerations

- If observed rollback frequency is high (>1/week), revisit whether the 5-minute floor is acceptable
- Quarterly rollback drill (parallel to restore drill) — file as future TD
- Migrate script + ADR to `jarvis-standards` once stable for 2+ sessions

## References

- AUDIT-7: `docs/audit/GAP_ANALYSIS_v2.md`
- Backup recovery: `docs/adr/ADR-0013-backup-recovery.md`
- Deploy script (symmetric reference): `scripts/jarvisalpha_deploy.sh`
- gh CLI revert docs: `gh pr revert --help`
