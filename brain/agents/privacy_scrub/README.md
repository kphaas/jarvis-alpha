# Privacy-Scrub Agent

Alpha privacy agent foundation for inventorying and removing public personal
data through guarded, human-approved workflows.

## Status

P1 is deployed. P2-A adds app-side crypto and repository helpers for intake,
but the package remains inert from an operator/runtime perspective. The runner
is default-off and still no-ops even if enabled. No scanner, route, executor,
notification, opt-out send, or court-filing path is wired.

## Placement

The core agent lives in `jarvis-alpha` because it handles identity, minors,
legal/court workflows, approval gating, and security evidence. Financial may
later show read-only posture data, but it should not own the privacy executor.

## Current Guarantees

- Minors require a guardian in Python and in the DB.
- Minor external actions are T5 and manual-only.
- Adult opt-out sends are T4 at minimum.
- Sensitive-payload or ID-document targets are T5.
- Court filing actions are T5; court-motion drafts are T4.
- PII and legal detail payloads are encrypted-only in schema.
- Identity tuples use keyed HMAC digests, not raw SHA-256 handles.
- Sensitive tables use `ENABLE ROW LEVEL SECURITY` and `FORCE ROW LEVEL SECURITY`.
- Action events are append-only.
- No public SQL decrypt helper is created.
- P2-A repository writes are transaction-scoped and expect an RLS-bound
  connection from the caller.

## File Map

```text
brain/agents/privacy_scrub/
├── __init__.py
├── crypto.py
├── repository.py
├── subjects.py
├── identity.py
├── targets.py
├── policy.py
├── state.py
├── runner.py
└── data/
    ├── brokers.yaml
    ├── social_targets.yaml
    └── ga_court_targets.yaml
```

## Deferred Work

- P2-B: `/v1/privacy/*` routes and approval classification.
- P2-C: operator intake UI.
- P3: local-only inventory scanner and target cache refresh.
- P4: opt-out action lifecycle through `alpha_approval_queue`.
- P5: Pushover/ChatOps notifications for T4/T5 actions.
- P6: counsel-reviewed Georgia court drafting playbooks.
