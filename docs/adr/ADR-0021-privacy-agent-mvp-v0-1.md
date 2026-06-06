# ADR-0021: Privacy Agent MVP v0.1 Boundary

## Status

Proposed

## Context

P1 through P3-G now provide a complete local privacy workflow in Alpha: subject
intake, target selection, draft packet creation, approval handoff, approved
action queue, manual disposition, manual verification, case timeline, and local
case report.

The product needs an MVP marker before moving into any executor or
public-internet behavior. Without a boundary, future work could blur manual
tracking with automated opt-out execution.

## Decision

Mark Privacy Agent MVP v0.1 as a local-only, human-approved workflow.

The MVP includes the operator surfaces and append-only ledger needed to create,
approve, handle, verify, and report on privacy actions. It intentionally stops
before public-internet scanning, broker form submission, evidence upload, court
filing, scheduled runners, or action executors.

Any future executor phase must be a separate ADR and PR series with explicit
approval-gateway rules, egress review, target allowlisting, evidence handling,
and rollback controls.

## Consequences

- The current product can be used for manual privacy removal tracking.
- MVP completion is testable without sending data to third parties.
- Sensitive notes and evidence references remain encrypted payloads.
- The next major phase is executor design, not incremental hidden automation.
- Operators have a clear runbook and release marker for live smoke evidence.
