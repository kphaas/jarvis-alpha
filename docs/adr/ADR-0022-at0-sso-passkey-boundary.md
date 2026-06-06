# ADR-0022: AT-0 SSO And Passkey Boundary

## Status

Proposed

## Context

Alpha is becoming the authority for AT-0 operator identity. Helm already reads
Alpha session broker state, and Privacy Agent MVP v0.1 depends on Alpha profile
PINs, approval unlocks, and admin session claims.

The current PIN flow is useful for local operator control, but it is not the
right long-term foundation for cross-domain AT-0 sign-on. Passkeys should be
introduced as an Alpha-owned authentication factor, not separately inside every
AT-0 app.

## Decision

AT-0 SSO remains Alpha-owned.

Alpha will expose one session broker contract for AT-0 apps. Apps may render
their own surfaces, but they must trust Alpha-issued session state instead of
storing separate app passwords or independent passkey credentials.

Passkey/WebAuthn support will be introduced in a separate implementation phase:

- Alpha stores passkey credentials and challenge state.
- Alpha validates passkey ceremonies and issues Alpha sessions.
- Family, Financial, Helm, Privacy, and future AT-0 apps consume Alpha session
  broker grants.
- PIN remains available as a local fallback until passkey recovery, device loss,
  and bootstrap flows are reviewed.

## Required Implementation Controls

- Store passkey credentials in Alpha under FORCE RLS or platform-admin-only
  tables.
- Keep challenge state short-lived and single-use.
- Bind ceremonies to the intended AT-0 relying-party/domain model.
- Never log credential IDs, challenge material, PINs, or authenticator payloads.
- Add explicit recovery and device-loss runbooks before disabling PIN fallback.
- Preserve approval-gateway checks for Privacy, Keyturner, and other protected
  routes after passkey login.

## Out Of Scope For This ADR

- Browser autofill/passkey UI implementation.
- Replacing PIN unlocks for approvals.
- Sharing Family app credentials directly.
- Any relaxation of Privacy Agent approval or no-outbound boundaries.

## Consequences

- Alpha remains the single identity authority for AT-0.
- Apps can converge on one SSO model without duplicating auth state.
- Passkey work can proceed safely after the MVP hardening pass, with clear
  recovery and approval boundaries.
