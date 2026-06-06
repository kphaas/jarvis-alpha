# ADR-0022: AT-0 SSO Alpha Session Broker

Date: 2026-06-06
Status: accepted

## Context

AT-0 is moving from separate PIN gates per domain toward one operator identity
flow. Alpha already owns identity, policy, approval, audit, Gateway egress, and
security posture. Helm is the unified workspace and must not become a second
auth authority.

The first live Helm bridge uses Alpha's `alpha_session` HttpOnly cookie and the
Endpoint `/alpha` reverse proxy. That proves browser SSO is possible, but it
does not yet provide a stable broker contract that domain workspaces can ask:
"who is signed in, what can this session read, and when does it expire?"

## Auth Inventory

| System | Current browser auth | Token storage | Current SSO fit |
|---|---|---|---|
| Alpha | Profile PIN -> RS256 JWT | Alpha UI stores bearer token in `localStorage`; Alpha also sets `alpha_session` HttpOnly cookie | Authority. Source of truth for SSO decisions. |
| Helm | No separate login | No bearer token storage; sends cookies through same-origin `/alpha` proxy | First SSO consumer. |
| Family | Household/member PIN -> RS256 JWT | Family UI stores `family_token` in `localStorage`; session version revokes tokens | Needs migration to Alpha-brokered browser session before shared SSO. |
| Financial | PIN -> browser JWT cookie + CSRF cookie | HttpOnly browser session cookie, separate from Alpha | Good future consumer, but money paths need step-up. |
| Forge | No first-class PIN/JWT gate for browser UI; service integrations use internal tokens/OAuth where configured | Mixed service tokens and operator UI with no SSO boundary | Needs auth hardening before SSO trust. |
| Medical | No implemented repo beyond local editor settings found in this pass | None found | Greenfield; should start behind Alpha broker. |

## Decision

Alpha is the AT-0 identity provider for browser SSO.

Phase 1 adds an authenticated `GET /v1/auth/session` broker endpoint. It returns
only session metadata:

- Alpha authority marker.
- Principal role/profile id, workspace id, content rating, and child age when present.
- Session expiry if the JWT has `exp`.
- Per-application grants, starting with Helm.

The broker endpoint does not return JWTs, cookies, PIN state, display names, raw
approval details, or domain data. Helm uses this endpoint as a read-only SSO
probe before reading scoped Alpha summaries.

## Consequences

- Helm can show whether Alpha SSO is live without storing browser-readable
  credentials.
- Alpha remains the only source of truth for Helm's authorization state.
- Existing Alpha PIN login, bearer-token API calls, and Helm summary behavior
  remain backward compatible.
- Future domain apps can converge on the same broker shape instead of copying
  Alpha tokens into each UI.

## Follow-Up Phases

| Phase | Scope |
|---|---|
| P2 | Add session revocation/logout inventory and align Alpha cookie expiry with operator policy. |
| P3 | Define Alpha app-token exchange with audience, nonce, TTL, and JWKS before any domain app consumes exchanged tokens. |
| P4 | Migrate Family from `localStorage` bearer token toward brokered session cookies. |
| P5 | Add passkeys/WebAuthn for adult/admin login; keep PIN as fallback and T4/T5 step-up. |

## Risks And Mitigations

| Risk | Mitigation |
|---|---|
| Broker leaks too much identity detail | Response omits JWT, cookie value, PIN state, and display name. |
| Helm starts treating SSO as execution authority | Broker reports grants only; Alpha summary and approval routes still enforce scopes. |
| Domain apps copy current Alpha JWTs | Token exchange is explicitly deferred until audience-bound tokens and JWKS are designed. |
| Child or custody contexts get over-permissioned | Non-admin sessions without `helm.read` report `missing_scope`; no Helm capabilities are granted. |

## Rollback

Remove `GET /v1/auth/session` and its route classification. Existing PIN login,
`POST /v1/auth/session-cookie`, and `/v1/helm/summary` continue to work.
