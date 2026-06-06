# ADR-0019: Alpha-Owned Beacon Internet Scout

Date: 2026-06-06

## Status

Accepted

## Context

Local LLM flows need current public internet facts, but raw web pages are
untrusted input. A malicious page can contain indirect prompt-injection text
that tries to override system instructions, call tools, expose secrets, poison
memory, or trigger downstream actions.

Alpha already owns approvals, policy, audit posture, and the rule that Brain
does not call public internet hosts directly. Public egress belongs behind
Gateway-owned routes.

## Decision

Create an Alpha-owned internet evidence broker named Beacon.

Beacon will be implemented as:

- `brain.services.internet_scout` for reusable policy, safety, sanitizer,
  planning, and evidence contracts;
- `brain.agents.internet_scout` for the future inert-to-active agent package;
- Gateway-owned internet egress endpoints in later phases;
- read-only evidence APIs for other JARVIS systems after review.

P0/P1 is intentionally no-outbound. It creates the ADR, package skeleton, brand
asset, deterministic guards, and tests only.

## Architecture

```text
Consumer service or local LLM flow
  -> Alpha Brain Beacon API
  -> Brain policy and evidence service
  -> Gateway internet egress route
  -> search / fetch / extract / crawl / browser-use tool
  -> quarantined raw content
  -> sanitized structured evidence
  -> cited answer or approval request
```

Brain remains the policy/evidence owner. Gateway remains the public egress
owner. Other JARVIS repos consume read-only evidence through Alpha instead of
getting direct browser or search credentials.

## Approval Policy

- Search, fetch, and extraction are read-only T2 when URL and content guards
  pass.
- Bounded crawl is T3 with strict page and depth limits.
- Interactive browser-use is disabled in P1.
- Future browser-use is T4 by default and T5 for privacy, legal, financial, or
  minor-related work.

## Prompt-Injection Boundary

Raw web content is data, not instructions. Beacon never treats fetched page text
as authority to call tools, update memory, reveal secrets, change policy, or
perform actions.

The sanitizer labels injection markers and returns structured untrusted content.
The action layer must evaluate the original user/system request, not directives
found inside fetched content.

## Four-Lens Review

| Lens | Review |
|---|---|
| Architecture | Alpha owns policy/evidence; Gateway owns egress; consumers get read-only evidence. |
| Security | URL, redirect, content, browser-use, and prompt-injection gates exist before outbound code. |
| Operations | P1 has no runtime blast radius; later phases add audit, rate limits, posture, and run ledger. |
| Data Quality | Evidence contracts require source URL, host, content hash, timestamps, citations, and confidence. |

## Gap Analysis

| Gap | Control |
|---|---|
| SSRF to internal hosts | Block localhost, non-global IPs, Tailscale hosts, local/internal suffixes, credentials, odd schemes, and redirect chains. |
| Prompt injection | Sanitize and label raw content as untrusted data; never execute web-provided instructions. |
| Browser overreach | Browser-use is disabled in P1 and must later route through Alpha approvals. |
| Memory poisoning | No automatic memory/RAG ingest; evidence promotion is a separate reviewed phase. |
| Supply-chain risk | P1 adds no crawler dependencies; later Crawl4AI/browser-use additions must be pinned and audited. |
| Cross-repo misuse | Consumers call Alpha for evidence; they do not import Beacon internals or hold internet credentials. |

## Consequences

Beacon starts with enterprise guardrails instead of a fast scraper. Later phases
can safely add search, fetch, crawl, and browser-use capabilities because the
policy and evidence boundary is already explicit and testable.
