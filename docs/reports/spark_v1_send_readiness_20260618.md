# Spark v1 Approved-Send Readiness - 2026-06-18

Status: production-ready for operator-approved iMessage sends
Owner: Ken
Runner: Codex on Brain
Scope: Spark draft -> approval queue -> encrypted outbox -> approved send

## Decision

Spark v1 is ready for normal operator-approved sends. Live test sends to Sweta should stop; future smoke checks use the non-live canary unless Ken provides real message content and explicitly approves the send.

## Evidence

| Check | Result |
|---|---|
| Brain Alpha HEAD at verification | `f680c27` |
| Runtime readiness | `/v1/spark/imessage/readiness` returned `ready=true`, 10/10 checks passed |
| Approved target | `ken-imessage-sweta-20260605-001`, one-to-one iMessage, parent-minor context approved |
| Successful approved send | Outbox `71c0b685-3052-4271-aadb-3d80bd2a4b2e` status `sent` |
| Duplicate/unsafe retry behavior | Retry rejected with `409 spark_outbox_already_final` during live verification |
| Send attempt count | `1` |
| Sent timestamp | `2026-06-18T18:57:32.694186+00:00` |
| Pending Spark approvals | `0` via `/v1/approvals/pending` |
| Non-live canary | `scripts/smoke_spark_send_readiness.sh` checks readiness/target/outbox/approvals only |
| Canary send capability | No `imessage.send` scope; no approved-send endpoint call |
| BlueBubbles helper | Deferred; direct BlueBubbles runtime path is sufficient for v1 and readiness is green |

## Operating Policy

- Do not send more live readiness/test texts to Sweta.
- Use `bash scripts/smoke_spark_send_readiness.sh` for post-deploy Spark send readiness checks.
- `bash scripts/smoke_spark_drafts.sh` remains draft-only. `SPARK_DRAFT_SMOKE_QUEUE_APPROVAL=true` may queue an approval/outbox row for review, but it still must not send.
- A live Spark send requires real message content, an explicit operator approval, a persisted outbox row, and the scoped approved-send route.

## Remaining Work

| Priority | Item | Owner | Date |
|---|---|---|---|
| P0 | Run the first non-test, normal-workflow approved draft when Ken supplies real content | Ken/Codex | 2026-06-18 |
| P1 | Keep BlueBubbles helper/private API enablement deferred unless direct runtime stops meeting v1 needs | Ken/Codex | 2026-06-18 |
| P2 | Periodically archive/expire historical failed/pending Spark outbox rows if they become noisy | Codex | TBD |

## Result

Production readiness is complete for Spark v1 send mechanics. The only intentionally unperformed action is a real personal message send, because no real message content was provided in this step.
