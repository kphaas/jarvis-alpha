# Privacy Agent Readiness Proof - 2026-06-17

Status: pass for live manual-control MVP, outbound automation blocked
Owner: Ken
Runner: Codex on Air, live checks against Brain and Sandbox
Scope: Privacy Agent manual workflow, approval handoff, verification, restore/RLS proof

## Verdict

| Decision | Result |
|---|---|
| Manual Privacy Agent workflow | Pass |
| Live human approval handoff | Pass |
| Manual disposition + verification | Pass |
| Evidence manifest | Complete |
| Pending privacy approvals after proof | 0 |
| Outbound automation | Blocked by design |
| Production readiness | Manual MVP ready for review; autonomous outbound not approved |

## Live Smoke Evidence

| Check | Result |
|---|---|
| Smoke command | `.venv/bin/python scripts/smoke_privacy_agent.py --approval-mode operator --approval-wait-seconds 900` |
| Smoke run ID | `20260617232834` |
| Approval queue ID | `12420418-58ab-4ab3-8838-966e7a5be9ad` |
| Case draft ID | `f665e045-136f-4a48-9928-7a51983211df` |
| Action ID | `92f95e0c-c938-4965-9cc1-eee7a1ed3335` |
| Target | `beenverified` |
| Timeline events | 5 |
| Case status | `completed` |
| Evidence manifest | `complete` |
| Missing evidence count | 0 |
| Pending privacy approvals | 0 |

Live smoke output:

```json
{"result":{"action_id":"92f95e0c-c938-4965-9cc1-eee7a1ed3335","case_id":"f665e045-136f-4a48-9928-7a51983211df","evidence_status":"complete","outbound_enabled":false,"run_id":"20260617232834","target_id":"beenverified","timeline_events":5},"status":"passed"}
```

## Safety Evidence

| Check | Result |
|---|---|
| Removal-control mode | `manual_control_plane` |
| Outbound enabled | `false` |
| Live summary timestamp | `2026-06-17T23:34:10.736102Z` |
| Registered privacy targets | 15 |
| Broker targets | 10 |
| Approved actions terminal | 8 |
| Pending approvals total | 0 |

This proof did not enable outbound submission, browser automation, broker form
submission, email sending, or any third-party privacy request execution.

## Restore + RLS Evidence

| Check | Result |
|---|---|
| Restore drill run ID | `2026-06-17_225312` |
| Restore host | `jarvis-sandbox` |
| Source dump | `jarvis_alpha_2026-06-17_063000.dump.gpg` |
| Restore status | `pass` |
| Table count | `97/97` |
| Privacy tables restored | 14 |
| Privacy FORCE RLS tables | 14 |
| Restore fail reasons | none |

Restore report:

```json
{"run_id":"2026-06-17_225312","host":"jarvis-sandbox","status":"pass","source_dump":"jarvis_alpha_2026-06-17_063000.dump.gpg","table_count":97,"ref_table_count":97,"row_counts":{"alpha_privacy_tables":"14","alpha_privacy_force_rls_tables":"14"},"fail_reasons":""}
```

## Local Verification

| Command | Result |
|---|---|
| `python -m pytest tests/test_privacy*.py tests/test_backup_scripts.py -q` | `205 passed, 6 skipped` |
| `python -m pytest tests/test_privacy_agent_smoke_script.py tests/test_backup_scripts.py -q` | `44 passed` |
| `python -m ruff check scripts/smoke_privacy_agent.py tests/test_privacy_agent_smoke_script.py tests/test_backup_scripts.py` | pass |
| `bash -n scripts/restore_drill_alpha.sh` | pass |
| `git diff --check` | pass |

## Artifacts

| Artifact | Purpose |
|---|---|
| `docs/adr/ADR-0028-privacy-agent-executor-egress-boundary.md` | Keeps outbound executor blocked until explicit executor-phase gates are met |
| `scripts/smoke_privacy_agent.py` | Synthetic manual workflow smoke with PIN mode and operator-approval mode |
| `tests/test_privacy_agent_smoke_script.py` | Guards smoke behavior, no secret leaks, and no remote ALPHA_PIN fallback |
| `docs/privacy/PRIVACY_AGENT_MVP_RUNBOOK.md` | Operator runbook for manual and automated smoke paths |
| `scripts/restore_drill_alpha.sh` | Restore drill now asserts Privacy Agent tables and FORCE RLS counts |
| `tests/test_backup_scripts.py` | Static guard for restore privacy/RLS proof checks |

## Non-Go Criteria For Outbound Automation

Outbound Privacy Agent execution remains blocked until a separate reviewed phase
ships all of the following:

- Target allowlist and per-target adapter profiles.
- Gateway-owned egress only, never direct Brain outbound.
- Approval hash binding from draft to execution.
- Dry-run default with reviewed payload preview.
- Encrypted evidence capture and digest-only UI proof.
- Rate limits, idempotency keys, and rollback/kill switch.
- Manual-only handling for minor, legal, and public-record edge cases.

## Post-Proof P5-A Delta

After this live proof, P5-A added the local removal-request lifecycle ledger:
`alpha_privacy_removal_requests` and `alpha_privacy_removal_request_events`.
Future restore drills therefore expect 16 Privacy Agent tables with FORCE RLS,
while this report's restore evidence records the pre-P5-A live proof count of 14.
The added lifecycle ledger remains local-only and does not enable outbound
execution.

## Post-Proof P5-B Delta

P5-B adds a dry-run executor proof path, not live automation. Alpha can prepare
an encrypted Gateway dry-run envelope for queued/approved removal requests and
record hash-only proof metadata. The only egress path is Gateway
`/v1/cloud/privacy/removal/dry-run`, which is a no-op validator requiring
`outbound_enabled=false`, `would_send=false`, and no allowed effects. No broker
form, browser, email, SMS, or public API execution is enabled by this delta.

## Post-Proof P5-C Delta

P5-C adds a one-target Gateway live-preflight proof for BeenVerified only. Alpha
requires a queued request, existing P5-B dry-run proof, and a fresh approved
`alpha_approval_queue` binding decided within 15 minutes before calling Gateway
`/v1/cloud/privacy/removal/live-preflight`. Gateway defaults to `live_disabled`
unless `PRIVACY_EXECUTOR_LIVE_ENABLED=true`; when enabled, it performs only one
fixed GET to `https://www.beenverified.com/app/optout/search`. It still returns
`would_send=false`, does not transition requests to `sent`, and blocks browser
automation, email, SMS, broker form submit, and PII payload submit.
