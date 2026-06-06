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

P0/P1 was intentionally no-outbound. It created the ADR, package skeleton,
brand asset, deterministic guards, and tests only. P2/P3 added reviewed
Gateway-owned search/fetch egress and RLS-protected evidence persistence while
preserving the same prompt-injection and Brain-egress boundaries. P4/P5 added
main-text extraction and approval-queue-only browser task requests. P6/P7 added a
local-LLM citation envelope and bounded same-host crawl without enabling browser
automation, scheduling, memory ingest, or outbound actions. P8/P9 added the
approval-verified browser runner boundary and Forge/Family/Financial consumer
routes. P10/P11 add reviewed evidence-to-memory promotion and a fail-closed
Playwright adapter factory with screenshot storage and hourly run limits, while
scheduled agent runtime remains deferred. The MVP production closeout adds
Gateway-owned search provider selection: Brain requests `auto`, Gateway prefers
Brave when configured, and otherwise uses the first-party Perplexity Search API
when `PERPLEXITY_API_KEY` is present. Explicit provider requests still fail
closed if that provider's key is missing.

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
- Interactive browser-use execution requires an approved, unexpired queue row
  matching the exact normalized Beacon browser request hash.
- Browser execution is T4-only, same-host, screenshot-required, quota-limited,
  and adapter-based. The default adapter fails closed.
- The Playwright adapter can only run when explicitly configured with the
  reviewed runtime name, screenshot directory, timeout, and expected dependency
  version.
- Memory promotion is a separate T4-style reviewed write path. It requires
  stored Beacon evidence, a claim index, a source content hash, clean proposed
  fact text, and explicit approve/reject review.
- T5 privacy, legal, financial, and minor-related browser work remains deferred.
- Forge, Family, and Financial consumers use policy-scoped routes; Family and
  Financial are forced to sensitive lanes and cannot use browser/crawl.

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
| Architecture | Alpha owns policy/evidence; Gateway owns egress; consumers get read-only evidence through Beacon contracts. |
| Security | URL, redirect, content, browser-use approval, sandbox policy, prompt-injection, and memory-promotion gates exist before runtime code. |
| Operations | Browser runner defaults to unavailable unless the reviewed runtime is configured; approvals are consumed only after success; hourly quotas cap blast radius. |
| Data Quality | Evidence contracts require source URL, host, content hash, timestamps, citations, confidence, screenshot review markers, and reviewed semantic-memory results. |

## Gap Analysis

| Gap | Control |
|---|---|
| SSRF to internal hosts | Block localhost, non-global IPs, Tailscale hosts, local/internal suffixes, credentials, odd schemes, and redirect chains. |
| Prompt injection | Sanitize and label raw content as untrusted data; never execute web-provided instructions. |
| Browser overreach | Browser-use execution requires exact approval-row verification, T4-only sandbox policy, same-host observation checks, and screenshots; default adapter fails closed. |
| Memory poisoning | No automatic memory/RAG ingest; promotion requires stored evidence, clean fact text, source hash, claim binding, and explicit review. |
| Supply-chain risk | Bounded crawl uses the existing guarded fetch path; browser runtime is opt-in and version-checked before use. |
| Cross-repo misuse | Consumers call Alpha policy-scoped routes; they do not import Beacon internals or hold internet credentials. |
| Sensitive consumers | Family and Financial force minor/financial sensitivity and block browser/crawl in P9. |
| Runtime operations | P11 adds code-level adapter wiring, but production deployment still needs package installation, browser binary provisioning, screenshot retention, and alerting. |
| Search provider availability | Gateway owns provider selection. `auto` prefers Brave and falls back to Perplexity Search; no provider key still fails closed. |

## Consequences

Beacon starts with enterprise guardrails instead of a fast scraper. Later phases
can safely add deeper extraction, crawl, and browser-use capabilities because
the policy and evidence boundary is already explicit and testable.
