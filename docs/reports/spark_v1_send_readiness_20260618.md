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

## 2026-06-27 Closeout Evidence

| Check | Result |
|---|---|
| Real operator-approved send | Ken supplied exact recipient/content and approved one live Spark send |
| Normal UI/outbox path | Spark approval queue -> Approvals PIN gate -> `Send approved` |
| Successful approved send | Outbox `4fd54388-a83c-4ec1-a5ad-d2370f9b176b` status `sent` |
| Send attempt count | `1` |
| Phone receipt | Ken confirmed Sweta received exactly one message entry |
| Duplicate/unsafe behavior | Older duplicate outbox remained `pending_approval`, attempts `0` |
| Stale duplicate cleanup | Add metadata-only outbox cancel route; use it only on stale non-final rows |

## Operating Policy

- Do not send more live readiness/test texts to Sweta.
- Use `bash scripts/smoke_spark_send_readiness.sh` for post-deploy Spark send readiness checks.
- `bash scripts/smoke_spark_drafts.sh` remains draft-only. `SPARK_DRAFT_SMOKE_QUEUE_APPROVAL=true` may queue an approval/outbox row for review, but it still must not send.
- A live Spark send requires real message content, an explicit operator approval, a persisted outbox row, and the scoped approved-send route.
- Sweta-as-principal remains draft-only until Sweta-approved source intake exists and 3-5 reviewed shadow drafts pass.

## Remaining Work

| Priority | Item | Owner | Date |
|---|---|---|---|
| P0 | Done: first real normal-workflow approved draft sent and receipt confirmed | Ken/Codex | 2026-06-27 |
| P1 | Use the outbox cancel route to retire stale duplicate pending rows after deploy | Codex | 2026-06-27 |
| P1 | Keep BlueBubbles helper/private API enablement deferred unless direct runtime stops meeting v1 needs | Ken/Codex | 2026-06-27 |
| P2 | Sweta principal: complete source intake, review 3-5 shadow drafts, then decide whether send flow is allowed | Ken/Sweta/Codex | TBD |

## Result

Production readiness is complete for Ken-operated Spark v1 send mechanics. Sweta-as-principal remains draft-only; do not enable sends until Sweta-approved source intake and shadow review are complete.
