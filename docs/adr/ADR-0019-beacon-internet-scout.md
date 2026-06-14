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
closed if that provider's key is missing. P13-P17 add production readiness
surfaces: Brain health and report-only retention endpoints, Gateway provider
health and circuit-breaker fallback, a production agent response envelope, and a
smoke/runbook path. Retention remains inventory-only; deletion requires a
separate reviewed change. Follow-up production readiness keeps recent evidence
failures as visible diagnostics while making the core dependency checks
database, Gateway, browser runtime, and retention authoritative for readiness.
The citation-quality hardening release adds a source-ranking gate for Helm Ask
and agent responses: official documentation/API queries require matching
official hosts, low-confidence/social results are excluded from prompt context,
and prompt-injection markers cause citation rejection before local models see
the evidence block. The research-quality release adds a deterministic research
planner, bounded multi-query Deep Beacon searches, stricter official-host
matching, and claim-support verification. Unsupported claims are stored as audit
evidence but excluded from local-model prompt context.
The Perplexity-quality search release adds provider fanout planning, deterministic
reranking, bounded extraction of top search results, and an explicit synthesis
contract. Brain still does not choose raw public egress hosts directly: fanout
uses Gateway provider hints, Gateway enforces configured provider credentials and
fallback, and extracted pages re-enter Beacon as untrusted evidence before any
local model sees them.
The production-quality search follow-up adds live canary-suite evaluation, a
bounded Deep Research report contract, and an explicit memory boundary. Beacon
can prove the positive Ask path repeatedly, return a report object for richer
research UX, and mark all internet evidence as evidence-store-only unless a
reviewed memory promotion is approved.
Research quality v2 makes the Deep Research contract more explicit: every plan
has a deterministic plan id, redacted subquestions, expected source types, and
stop criteria. Claim verification fails closed on clear negation, version, date,
unit, currency, and number mismatches. Research reports expose redacted coverage
counters and warnings so Helm and operators can see why Beacon answered,
limited, or refused verification without persisting raw page text.

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

Beacon is also registered as Alpha managed agent `internet_scout`. Helm Ask can
request `web_search` or `deep_research`, but Alpha still routes both through
Beacon's citation envelope. The chat surface never invokes browser automation;
browser work stays on the separate exact-match approval queue.

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

## Citation Quality Boundary

Beacon does not treat search-result rank as source authority. Before evidence is
injected into a local model prompt, citations are classified as `official`,
`primary`, `trusted_secondary`, `general`, `low_confidence`, or `rejected`.

Queries that ask for official docs, API references, SDKs, release notes, terms,
privacy policies, or status pages require official host matches when Beacon can
infer the vendor from the query. Non-matching sources remain stored as audit
evidence, but they are excluded from the answer context and counted as rejected
citations. The chat prompt receives `supported`, `weak`, or `insufficient`
source-quality status and must not present insufficient evidence as verified.

Deep research requests carry an explicit research plan with intent, search
budget, authority requirements, freshness requirements, and planned query
purposes. Normal web search remains a single Gateway search. Deep research can
issue several bounded Gateway search calls and merge the results into one
evidence packet.

Search plans also record provider strategy, provider hints, and extraction
budget. Deep research can fan out across Brave and Perplexity provider hints,
dedupe URLs, rerank by source quality plus cross-provider/query agreement, and
send only the top bounded URLs through Gateway extraction. If an explicit
provider is unavailable, Brain drops that fanout leg and falls back to Gateway
`auto` only when no explicit provider produced results.

Citation acceptance also requires deterministic claim support. Beacon compares
each stored claim with its citation text, rejects unsupported or number-mismatched
claims before prompt injection, and records verified/unsupported claim counters
for health and Helm visibility.

Local LLM and agent responses include a synthesis contract with one of three
behaviors: answer with citations, answer with limitations, or state that Beacon
could not verify the claim. This keeps answerability explicit and prevents a
model from silently upgrading weak search evidence into verified facts.

Deep Research responses also include a report contract with summary, key
findings, limitations, source hosts, and bounded markdown. The report is a
rendering aid for Helm/consumers, not a new trust boundary; accepted citations,
source quality, and synthesis behavior remain authoritative.

Search evidence has an explicit memory boundary: automatic memory writes are
not allowed, memory context is secondary to Beacon for current/public web
claims, and memory promotion must use the reviewed promotion route bound to
stored evidence, source hash, and claim.

## Four-Lens Review

| Lens | Review |
|---|---|
| Architecture | Alpha owns policy/evidence; Gateway owns egress; consumers get read-only evidence through Beacon contracts. |
| Security | URL, redirect, content, browser-use approval, sandbox policy, prompt-injection rejection, and memory-promotion gates exist before runtime code. |
| Operations | Browser runner defaults to unavailable unless the reviewed runtime is configured; approvals are consumed only after success; hourly quotas cap blast radius. |
| Data Quality | Evidence contracts require source URL, host, content hash, timestamps, citations, confidence, source-quality status, screenshot review markers, and reviewed semantic-memory results. |

## Gap Analysis

| Gap | Control |
|---|---|
| SSRF to internal hosts | Block localhost, non-global IPs, Tailscale hosts, local/internal suffixes, credentials, odd schemes, and redirect chains. |
| Prompt injection | Sanitize and label raw content as untrusted data; never execute web-provided instructions. |
| Citation spoofing | Official docs/API-style queries require inferred official hosts; weak/social/non-matching sources are stored for audit but excluded from prompt context. |
| Unsupported snippets | Claim-support verification excludes citations whose text does not substantiate the stored claim. |
| Search-result overtrust | Top ranked URLs are extracted and re-scored before prompt injection; snippets remain fallback discovery evidence only. |
| Provider monoculture | Deep research can fan out across Gateway providers and rerank cross-provider agreement without giving Brain direct provider credentials. |
| Browser overreach | Browser-use execution requires exact approval-row verification, T4-only sandbox policy, same-host observation checks, and screenshots; default adapter fails closed. |
| Memory poisoning | No automatic memory/RAG ingest; promotion requires stored evidence, clean fact text, source hash, claim binding, and explicit review. |
| Search-to-memory drift | Local LLM, chat, and agent contracts carry `automatic_memory_write_allowed=false` and promotion-review metadata. |
| Supply-chain risk | Bounded crawl uses the existing guarded fetch path; browser runtime is opt-in and version-checked before use. |
| Cross-repo misuse | Consumers call Alpha policy-scoped routes; they do not import Beacon internals or hold internet credentials. |
| Sensitive consumers | Family and Financial force minor/financial sensitivity and block browser/crawl in P9. |
| Runtime operations | P11 adds code-level adapter wiring, but production deployment still needs package installation, browser binary provisioning, screenshot retention, and alerting. |
| Search provider availability | Gateway owns provider selection. `auto` prefers Brave and falls back to Perplexity Search; no provider key still fails closed. |
| Production visibility | P13 health reports database contract, Gateway provider state, browser runtime state, recent evidence status, and retention inventory without exposing secrets. |
| Provider brownouts | P14 tracks per-provider failures in Gateway memory, opens a short cooldown circuit, and fails closed when no configured usable provider remains. |
| Evidence lifecycle | P15 reports old evidence rows and screenshot files only; deletion is intentionally out of scope for MVP. |
| Local LLM misuse | P16 returns citations, confidence, explicit untrusted-content warnings, and not-verified notes instead of raw authority. |
| Operator readiness | P17 adds a smoke script and rollback runbook before deploy approval. |
| Readiness noise | Recent evidence failures remain diagnostic warnings; they do not block readiness when database, Gateway, browser runtime, and retention are healthy. |
| Quality regression detection | Helm Ask smoke supports a multi-case canary suite that checks supported official evidence, stale-memory rejection, synthesis behavior, untrusted-content metadata, and memory-write blocking. |

## Consequences

Beacon starts with enterprise guardrails instead of a fast scraper. Later phases
can safely add deeper extraction, crawl, and browser-use capabilities because
the policy and evidence boundary is already explicit and testable.
