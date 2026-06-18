# ADR-0028: Privacy Agent Executor And Egress Boundary

Date: 2026-06-17

Status: Proposed

Update 2026-06-18: P5-B implements the dry-run proof slice only. Alpha records
an encrypted dry-run envelope and calls Gateway `/v1/cloud/privacy/removal/dry-run`,
which validates a no-op request with `outbound_enabled=false` and
`would_send=false`. P5-C adds a one-target BeenVerified live preflight behind
`PRIVACY_EXECUTOR_LIVE_ENABLED`; it can perform only a fixed Gateway GET to the
opt-out page after a fresh approval binding. This does not approve broker form
submission or live removal dispatch.

## Context

Privacy Agent MVP v0.1 is a local-only, human-approved workflow. It can create
encrypted subjects, select local targets, draft review packets, submit approval
handoffs, show approved actions, record manual disposition, record verification,
and produce timeline/report evidence.

The next product step is executor work: public-internet discovery, broker
submission, email/SMS, evidence upload, recurring follow-up, search deindexing,
and public-record handling. Those behaviors move from local bookkeeping into
real external action, so they need a separate boundary before any implementation
can be considered production-ready.

## Decision

Keep Privacy Agent outbound-disabled until a dedicated executor phase ships with
all of these gates:

- A target allowlist that names every supported broker/search/court/public-record
  destination and the exact action types allowed for that destination.
- Gateway-owned public egress. Brain may request policy-approved work, but Brain
  must not directly scrape websites, submit forms, send email/SMS, or call public
  hosts for privacy removal.
- Approval-gateway verification immediately before execution. T4/T5 approval
  rows must match the exact normalized action hash, target id, subject id, and
  requested executor operation.
- Dry-run mode as the default for every executor. Production execution requires
  an explicit environment gate and a fresh approval row.
- A one-target live-preflight exception may verify Gateway reachability only
  when it is target allowlisted, kill-switch enabled, fresh-approval-bound, and
  still returns `would_send=false`.
- Evidence capture before and after execution, stored as encrypted payloads and
  digest-only UI metadata. No raw PII, credentials, IDs, or legal text may be
  written to logs or public response bodies.
- Per-target rate limits, retry limits, and idempotency keys so repeated smoke
  or operator runs cannot spam brokers or duplicate legal requests.
- Minor/legal/court/public-record work remains manual-only until counsel-reviewed
  playbooks and a separate ADR approve those lanes.
- Rollback controls that can disable executor dispatch without removing the
  manual Privacy Agent UI or historical ledger.

## Architecture

```text
Privacy operator
  -> Alpha /privacy manual workflow
  -> Alpha approval queue
  -> executor preflight verifier
  -> Gateway egress adapter
  -> approved external target
  -> encrypted evidence + append-only event ledger
```

Alpha owns policy, identity, approval linkage, event history, and encrypted
evidence. Gateway owns public egress and adapter runtime. The executor is a
thin dispatcher that can only consume approved, allowlisted, non-expired work.

## Non-Goals

- No hidden public-internet scanner in the current MVP.
- No broker form submission without the executor gates above.
- No live preflight beyond the explicitly allowlisted BeenVerified GET.
- No email/SMS sender in Brain.
- No automated court filing or court-record modification in this phase.
- No automatic use of real child, legal, medical, or financial context.

## Production Gates

| Gate | Required Before Executor Enablement |
|---|---|
| Security | Egress review, target allowlist, approval hash binding, secret/log audit |
| Tests | Unit, route, dry-run integration, negative egress, idempotency, rollback |
| Observability | Per-run events, failure counters, queue age, target rate-limit visibility |
| Evidence | Encrypted pre/post evidence payloads, hashes in UI, no plaintext logs |
| Backup/restore | Restore drill proves privacy executor/evidence tables survive recovery |
| Operations | Env kill switch, dry-run default, documented smoke, rollback runbook |

## Consequences

- The current manual Privacy Agent can keep shipping safely while executor work
  is designed and reviewed separately.
- Operators get a clear production-readiness line: manual tracking is usable,
  outbound action is blocked until all executor gates are green.
- Later automation work can be broken into target-specific PRs without weakening
  the approval, egress, evidence, or rollback boundaries.

## Post-Proof P5-B Delta

P5-B adds a dry-run executor proof path, not live automation. Alpha can prepare
an encrypted Gateway dry-run envelope for queued/approved removal requests and
record hash-only proof metadata. The only egress path is Gateway
`/v1/cloud/privacy/removal/dry-run`, which is a no-op validator requiring
`outbound_enabled=false`, `would_send=false`, and no allowed effects. No broker
form, browser, email, SMS, or public API execution is enabled by this delta.

## Post-Proof P5-C Delta

P5-C adds a constrained live-preflight proof path, not live removal automation.
Alpha requires a queued BeenVerified request, an existing P5-B dry-run proof, and
a fresh approved `alpha_approval_queue` item decided within 15 minutes. Gateway
defaults to `live_disabled`; when `PRIVACY_EXECUTOR_LIVE_ENABLED=true`, Gateway
performs only a fixed GET to
`https://www.beenverified.com/app/optout/search`. Browser automation, email,
SMS, broker form submit, and PII payload submit remain blocked, and responses
must keep `would_send=false`.
