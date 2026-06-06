# ADR-0020: Helm Cookie Session For Alpha Summary

Date: 2026-06-06  
Status: accepted

## Context

Helm is deployed as a static operator workspace on Endpoint. It reads Alpha through a same-origin `/alpha` reverse proxy and must not store service tokens or browser bearer tokens.

Alpha's existing UI session stores the user JWT in `localStorage` and sends `Authorization: Bearer ...` on API calls. That works for Alpha's own UI, but Helm cannot safely read another origin's `localStorage`, and copying bearer tokens into Helm would violate the Helm session boundary.

## Decision

Alpha PIN login will continue returning the existing JSON token for the Alpha UI, and will also set an `HttpOnly`, `Secure`, `SameSite=Strict` `alpha_session` cookie containing the same signed JWT.

Alpha JWT middleware will accept:

- `Authorization: Bearer <jwt>` first, preserving existing clients.
- `alpha_session=<jwt>` cookie when no bearer header is present.

Alpha UI will refresh the cookie through the same-origin Endpoint `/v1/auth/session-cookie`
proxy when an existing `localStorage` session is still valid. That proxy response sets
the host-scoped Endpoint cookie, which Helm can send to its `/alpha` proxy without
reading or storing the bearer token.

## Consequences

- Helm can read scoped Alpha endpoints such as `/v1/helm/summary` through the Endpoint `/alpha` proxy without storing a JavaScript-readable token.
- Existing Alpha UI behavior remains backward compatible.
- Cookie scope is host-wide, so Endpoint ports can share the session while the cookie remains unavailable to JavaScript.
- Raw approval queues, writes, and unscoped Alpha APIs remain protected by existing JWT claims and scope checks.
- ADR-0022 extends this cookie bridge into an Alpha-owned SSO broker contract
  for Helm session/grant introspection.

## Non-Goals

- No service token injection at nginx.
- No bearer token storage in Helm.
- No new public auth bypass route.
- No relaxation of route scope checks.
