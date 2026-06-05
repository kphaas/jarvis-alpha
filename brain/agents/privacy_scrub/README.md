# Privacy-Scrub Agent

P1 foundation for a JARVIS Alpha privacy agent that inventories and removes
public personal data through guarded, human-approved workflows.

## Status

This package is inert. The runner is default-off and still no-ops even if
enabled. No scanner, route, executor, notification, or court-filing path is
wired in P1.

## Placement

The core agent lives in `jarvis-alpha` because it handles identity, minors,
legal/court workflows, approval gating, and security evidence. Financial may
later show read-only posture data, but it should not own the privacy executor.

## P1 Guarantees

- Minors require a guardian in Python and in the DB.
- Minor external actions are T5 and manual-only.
- Adult opt-out sends are T4 at minimum.
- Sensitive-payload or ID-document targets are T5.
- Court filing actions are T5; court-motion drafts are T4.
- PII and legal detail payloads are encrypted-only in schema.
- Identity tuples use keyed HMAC digests, not raw SHA-256 handles.
- Sensitive tables use `ENABLE ROW LEVEL SECURITY` and `FORCE ROW LEVEL SECURITY`.
- Action events are append-only.
- No public decrypt helper is created in P1.

## File Map

```text
brain/agents/privacy_scrub/
├── __init__.py
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

- P2: local-only inventory scanner and target cache refresh.
- P3: `/v1/privacy/*` routes and approval classification.
- P4: opt-out action lifecycle through `alpha_approval_queue`.
- P5: Pushover/ChatOps notifications for T4/T5 actions.
- P6: counsel-reviewed Georgia court drafting playbooks.
