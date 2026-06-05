# ADR-0016: Privacy-Scrub P2 Intake And Draft Workflow

## Status

Accepted

## Context

P1 added the Alpha-owned privacy-scrub package and database foundation. The live
Brain verification confirmed the privacy tables, FORCE RLS, action-tier trigger,
append-only action events, and approval queue linkage.

The next useful capability is not automated removal. It is controlled intake and
draft preparation so Ken can review exactly what would be sent or filed before
any external side effect exists.

## Decision

P2 is limited to intake, local target selection, encrypted storage, and draft
action creation.

P2 must not perform automated opt-out sending, public-internet scanning, account
login, court filing, or document upload.

P2-F extends the same boundary with a draft review inbox. It may decrypt stored
review-packet payloads in app code through `PrivacyCrypto` for an authenticated
adult/admin operator. It must not add SQL decrypt helpers, expose plaintext
subject profile fields, or create any outbound action path.

P2-G adds internal disposition controls for reviewed drafts: submit for Alpha
approval handoff or archive. The handoff creates internal approval queue state
only; it does not send opt-outs, scan public targets, file court documents, or
upload evidence.

## Scope

P2 may add:

- Brain-side privacy subject intake for adult and minor subjects.
- App-side encryption and digest helpers with explicit key versions.
- Storage repository code for `alpha_privacy_subjects` and
  `alpha_privacy_identity_tuples`.
- Target selection from bundled YAML and `alpha_privacy_targets_cache`.
- Draft action creation in `alpha_privacy_actions`.
- Append-only action events for draft lifecycle changes.
- Case draft list/detail routes for operator review.
- Internal draft disposition routes for approval handoff and archive.
- Tests for RLS assumptions, approval-tier mapping, digest/encryption behavior,
  minor guardian requirements, and no-outbound behavior.

P2 must not add:

- Scheduled runners.
- External broker scans.
- Automated email/web-form/API opt-out sends.
- Court filing automation.
- Financial integration.
- Decrypt SQL functions.

## Approval Rules

| Workflow | Tier | Behavior |
|---|---:|---|
| Store encrypted subject profile | T2 | Internal write with structured audit |
| Add identity tuple digest | T2 | Internal write with structured audit |
| Load bundled target registry | T1 | Local metadata only |
| Create adult opt-out draft | T2 | Draft only; no external send |
| Create minor opt-out draft | T4 | Requires adult review before draft is actionable |
| Submit reviewed draft for approval | T2/T4/T5 by action | Internal approval handoff only |
| Archive reviewed draft | T2 | Internal disposition only |
| Attach sensitive evidence or ID document reference | T5 | Admin confirmation required |
| External scan or verification | T4 adult / T5 minor | Out of P2 implementation scope |
| Send opt-out request | T4 adult / T5 minor | Out of P2 implementation scope |
| Court filing or motion | T5 | Out of P2 implementation scope |

## Data Handling

- Plaintext subject data enters only at the authenticated route boundary.
- P2 stores plaintext identity values only in encrypted payload columns.
- Matching values are stored as keyed HMAC digests with `hmac-sha256:` prefixes.
- Payload integrity hashes use `sha256:` prefixes.
- Key versions are required for all encrypted payloads and HMAC digests.
- The database must not expose a decrypt helper.
- Logs must include subject/action IDs, never names, DOBs, addresses, phone
  numbers, email addresses, PINs, or document contents.

## Implementation Sequence

1. Add a small `PrivacyCrypto` service.
   - Inputs: digest key, payload key, key versions.
   - Outputs: HMAC digests, ciphertext bytes, payload hashes.
   - Tests: deterministic HMAC, different-key separation, no blank keys.

2. Add a subject repository.
   - Writes through existing P1 tables.
   - Requires guardian for minor subjects.
   - Uses RLS-aware DB access.
   - Tests: adult insert, minor-with-guardian insert, minor-without-guardian
     rejection.

3. Add a route-level design for intake.
   - `POST /v1/privacy/subjects`
   - `POST /v1/privacy/subjects/{subject_id}/identity-tuples`
   - Admin/adult authenticated only.
   - No child-facing route.

4. Add local target selection.
   - Load bundled YAML.
   - Sync non-PII metadata into `alpha_privacy_targets_cache`.
   - Return target IDs and risk flags.

5. Add draft action creation.
   - Insert draft rows into `alpha_privacy_actions`.
   - Insert event rows into `alpha_privacy_action_events`.
   - Do not send anything externally.

6. Add draft disposition handoff.
   - Allow reviewed drafts to be submitted into Alpha approval queue state.
   - Allow reviewed drafts to be archived.
   - Keep both paths internal-only and append an action event.

## Consequences

- Ken gets a reviewable privacy workflow before any external side effects.
- Minor and court workflows stay behind higher approval tiers.
- P2 creates useful stored state that P3/P4 can consume without reworking the
  foundation.
- The system remains safe if P2 ships alone because no runner or outbound
  executor exists.

## Open Questions

- Which Alpha UI surface should host privacy intake: Security, Admin, or a new
  Privacy tab? Resolved by P2-C: a new Privacy tab.
- Should P2 expose decrypt-for-review through app code for Ken only, or defer
  all payload review until a later operator UI decision? Resolved by P2-F:
  app-side decrypt is allowed for review-packet payloads only, through
  authenticated adult/admin Privacy routes.
- Should reviewed drafts be actionable inside P2? Resolved by P2-G: only
  internal submit/archive disposition is allowed; external execution stays out
  of scope.
- Should sensitive evidence references point to an existing Alpha document store
  or remain external/manual in P2?
