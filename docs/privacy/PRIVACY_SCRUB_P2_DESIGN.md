# Privacy-Scrub P2 Design

## Goal

Turn the P1 foundation into a reviewable intake and draft workflow without
adding outbound behavior.

## Non-Goals

- No automated scraping.
- No automatic opt-out sending.
- No social account login.
- No court filing.
- No Financial integration.
- No scheduled runner.

## User Workflow

1. Ken opens the privacy intake surface.
2. Ken creates a subject profile for himself or a minor under guardianship.
3. The route encrypts the subject payload and stores only ciphertext, payload
   hashes, key versions, and HMAC identity tuple digests.
4. Ken selects local target categories: data brokers, social profiles, public
   records, or breach database references.
5. The system creates draft actions with risk flags.
6. Ken reviews drafts before any future PR adds external execution.

## System Flow

```text
Authenticated adult/admin
  -> Brain privacy route
  -> PrivacyCrypto service
  -> RLS-aware repository
  -> alpha_privacy_subjects
  -> alpha_privacy_identity_tuples
  -> alpha_privacy_actions
  -> alpha_privacy_action_events
```

## Data Contracts

### Subject Intake

Required:

- `role`: `adult` or `minor`
- `display_label`
- `jurisdiction`
- at least one identity tuple

Minor-only:

- `guardian_user_id`
- guardian consent event

Sensitive fields:

- name
- date of birth
- address
- phone
- email
- notes
- legal context

These fields must live only inside encrypted payloads or keyed digests.

### Target Selection

Targets come from bundled YAML and the non-PII target cache.

Risk flags:

- `supports_minors`
- `requires_sensitive_payload`
- `requires_identity_document`
- `opt_out_method`
- `jurisdiction`

### Draft Action

Draft rows should include:

- `subject_id`
- `target_id`
- `action_type`
- `approval_tier`
- encrypted draft payload
- payload hash
- payload key version
- status

Draft rows should not include:

- plaintext URLs tied to a subject
- plaintext identity values
- raw document contents
- outbound provider credentials

## Acceptance Criteria

- Adult subject intake stores encrypted payload and HMAC tuple digests.
- Minor subject intake requires guardian linkage.
- Target selection is local-only.
- Draft creation writes an append-only event.
- External scan/send paths remain impossible because no runner or executor is
  wired.
- Tests prove blank keys fail closed.
- Tests prove no route or service uses raw `fetch`, `requests`, `httpx`, SMTP,
  browser automation, or provider SDKs for P2.

## Test Plan

- Unit: crypto key validation, HMAC determinism, ciphertext non-plaintext.
- Unit: policy tiers for adult/minor/sensitive/court workflows.
- Repository: subject insert, identity tuple insert, draft action insert.
- Repository: minor-without-guardian rejected.
- Static: no outbound libraries imported by privacy-scrub P2 modules.
- Route: adult/admin auth required; child actor rejected.

## Rollout Plan

1. Ship P2 code behind no scheduled runner.
2. Run local and Brain test gates.
3. Verify no LaunchAgent or cron entry was created.
4. Verify P2 routes are classified in the approval gateway.
5. Keep P3/P4 blocked until Ken reviews the first stored draft examples.
