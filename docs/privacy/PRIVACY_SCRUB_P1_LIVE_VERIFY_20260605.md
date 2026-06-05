# Privacy-Scrub P1 Live Verification

Date: 2026-06-05
Commit: `fceccf4`
PR: `#249`
Database: `jarvis_alpha` on Brain

## Result

P1 is deployed and the database foundation is present.

## Checks

| Check | Result |
|---|---|
| Migration tracking row | `20260605_010000_privacy_scrub_foundations.sql` recorded in `schema_migrations` with source `runner` |
| Privacy tables | 7 `alpha_privacy_*` tables present |
| Sensitive table RLS | `alpha_privacy_subjects`, `alpha_privacy_identity_tuples`, `alpha_privacy_scans`, `alpha_privacy_discoveries`, `alpha_privacy_actions`, and `alpha_privacy_action_events` have RLS enabled and forced |
| Target cache RLS | `alpha_privacy_targets_cache` has no RLS by design; it stores non-PII registry metadata |
| Policies | 6 privacy policies present, each with `WITH CHECK` |
| Approval linkage | `alpha_privacy_actions.approval_queue_id` references `alpha_approval_queue.id` |
| Decrypt helper | No `public.privacy%decrypt%` function exists |
| Action-tier trigger | `trg_privacy_actions_enforce_tier` is enabled |
| Event immutability | update/delete blocker triggers are enabled on `alpha_privacy_action_events` |
| Scheduled runner | No JARVIS privacy-scrub LaunchAgent or plist exists |

## Live Query Summary

```text
migration  20260605_010000_privacy_scrub_foundations.sql  runner  applied=true

table alpha_privacy_action_events      rls=true  force_rls=true
table alpha_privacy_actions            rls=true  force_rls=true
table alpha_privacy_discoveries        rls=true  force_rls=true
table alpha_privacy_identity_tuples    rls=true  force_rls=true
table alpha_privacy_scans              rls=true  force_rls=true
table alpha_privacy_subjects           rls=true  force_rls=true
table alpha_privacy_targets_cache      rls=false force_rls=false

fk alpha_privacy_actions.approval_queue_id -> alpha_approval_queue.id
function privacy%decrypt%: 0 rows
```

## Interpretation

P1 is still inert. It created storage, policy, and approval-linkage foundations
but did not schedule a runner, expose a route, seed secrets, or implement any
outbound scan/send behavior.
