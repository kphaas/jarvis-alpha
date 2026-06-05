# ADR-0015: Privacy-Scrub Agent Lives In Alpha

## Status

Proposed

## Context

Privacy-scrub handles identity data, minors, public-record discovery, broker
opt-outs, and potential court-record sealing workflows. These actions need
approval-gateway integration, FORCE RLS storage, append-only evidence, and
security/operator review.

`jarvis-financial` owns trading, paper-readiness, Plaid, Spend, and Net Worth.
Those paths should not inherit legal/privacy executor responsibilities.

## Decision

The core privacy-scrub agent lives in `jarvis-alpha`.

`jarvis-financial` may later consume read-only privacy posture summaries, but it
must not own scanner, opt-out, court-drafting, approval, or storage execution.

## Consequences

- Alpha owns schema, policy, approval queue integration, audit evidence, and
  future routes.
- Financial stays focused on money workflows and cannot accidentally couple
  privacy operations to trading or portfolio logic.
- Minor and court workflows remain behind Alpha's review and approval gates.

## Follow-Up

- P2 should add local-only inventory scanning first.
- P3 should add routes and approval classifications.
- P4 should wire approved opt-out execution through `alpha_approval_queue`.
- Court filing remains draft-only unless Ken and counsel explicitly approve a
  later filing workflow.
