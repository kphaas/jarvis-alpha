# JARVIS Alpha

## Product

JARVIS Alpha is Ken's private operator console for local-first automation,
security review, approvals, and personal AI workflows.

## Privacy Agent Scope

The Privacy Agent helps an operator prepare and track privacy removal work for
data brokers and public-record targets. The MVP is a manual, human-approved
workflow: it stores encrypted subject data, creates local review packets,
requires approval, and tracks manual disposition and verification.

## Primary Users

- Ken as the adult/admin operator.
- Future trusted operators who must use the same approval and audit controls.

## Non-Negotiables

- Sensitive subject data stays encrypted at rest.
- Identity values are stored as keyed digests, not plaintext workflow fields.
- Approval happens before privacy actions move into the action queue.
- MVP workflows do not scrape, submit forms, send email, file court records, or
  run scheduled public-internet jobs.
- Operator notes and evidence references are encrypted; UI surfaces hashes and
  status metadata.

## Interface Principles

- Dense operator surfaces beat marketing copy.
- Status must describe the current workflow state, not the phase name.
- Controls should be disabled when the next state transition is not valid.
- Audit evidence should be easy to find without exposing sensitive payloads.
