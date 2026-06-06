# ADR-0017: Privacy-Scrub P3 Approval Handoff

## Status

Proposed

## Context

P2-G lets an adult/admin operator submit a reviewed privacy case draft into
`alpha_approval_queue`. The queue item is visible in the Alpha approvals surface,
but the approval card did not identify the linked privacy packet and approval
decisions did not update local privacy action state.

The next useful capability is the approval review handoff, not external
execution. Operators need to open the packet from the approval queue and record
whether the local draft actions are approved or rejected.

## Decision

P3-A links privacy approval queue items back to their case draft packet and
records approval decisions on `alpha_privacy_actions`.

Approving a `privacy_draft_handoff` queue item marks linked local privacy
actions as `approved` and appends `approved` action events. Denying the queue
item marks linked local privacy actions as `rejected` and appends `rejected`
events.

P3-D through P3-G extend the same local-only boundary after approval:

- P3-D records manual operator disposition for approved actions: handled,
  deferred, or blocked.
- P3-E records manual verification outcomes: confirmed, follow-up needed, or
  failed.
- P3-F exposes case timeline metadata from append-only action events.
- P3-G exposes a local JSON case report with action status, event hashes, and
  timestamps.

Operator notes and evidence references are stored as encrypted payloads plus
hashes. The UI and read APIs expose hashes and workflow metadata, not plaintext
note/evidence contents.

P3 must not send opt-outs, scan public targets, upload evidence, file court
documents, add a scheduled runner, or consume approved privacy actions through
an executor.

## Consequences

- The Approvals page can open the exact privacy packet before decision.
- Approval/denial state is preserved in the privacy action ledger.
- Approved privacy actions remain inert until a later phase adds a separately
  reviewed executor.
- Existing approval queue semantics stay centralized in `decide_approval`.
- Operators can track manual handling and verification without introducing
  public-internet side effects.
- Case reports are local JSON metadata only; document/PDF generation remains a
  later scoped decision.
