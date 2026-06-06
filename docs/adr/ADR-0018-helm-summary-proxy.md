# ADR-0018: Alpha-Owned Helm Summary Proxy

Date: 2026-06-06

## Status

Accepted

## Context

Helm is the unified AT0 workspace, but Alpha remains the authority for approvals,
policy, audit, service registry, and security posture. The first Helm connector
work showed that browser Helm can safely read public Alpha health endpoints, but
it must not hold service credentials or call auth-gated Alpha admin routes
directly.

Helm still needs an operator-safe summary of Alpha state: approval queue counts,
registry counts, agent posture counts, and Gateway/security posture signals.

## Decision

Alpha will expose a narrow read-only `GET /v1/helm/summary` endpoint.

The route:

- requires normal JWT auth plus `helm.read` scope or an admin/wildcard caller;
- uses an Alpha platform-admin RLS context only after scope validation;
- returns counts and posture states only;
- does not return raw approval descriptions, actor subjects, secrets, PHI, or
  domain payloads;
- is classified as `read` and `security_read` in the approval gateway registry.

## Consequences

Helm gets a stable authority summary without becoming a second control plane.
Alpha keeps policy, audit, and approval ownership. Future Helm mutation paths
must still submit proposed actions back through Alpha approval contracts instead
of writing domain state directly.

