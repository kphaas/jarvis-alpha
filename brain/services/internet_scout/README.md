# Beacon Internet Scout

Beacon is Alpha's read-only internet evidence broker. It lets local LLM flows
ask for public evidence without giving raw web pages authority over JARVIS
tools, memory, approvals, or secrets.

## Status

P0/P1 only:

- ADR and service contracts exist.
- Policy, URL/content safety, sanitizer, evidence, and planning helpers exist.
- No route is mounted.
- No Gateway internet endpoint is implemented.
- No search API, crawler, browser-use runner, memory ingest, or outbound action
  is wired.

## Placement

Brain owns policy, evidence contracts, and approval classification. Gateway must
own public egress. This preserves the existing Alpha invariant that Brain does
not call public internet hosts directly.

## Product Name

User-facing name: Beacon.

Code package: `brain.services.internet_scout`, kept descriptive so other Alpha
services can depend on the contracts without depending on brand language.

## Deferred Work

- P2: Gateway search/fetch endpoints.
- P3: evidence persistence under RLS/FORCE RLS.
- P4: extraction path with pinned dependencies.
- P5: approval-gated browser-use path.
- P6: consumer integrations for local LLM, Forge, Family, and Financial.
