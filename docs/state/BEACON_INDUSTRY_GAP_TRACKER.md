# Beacon Industry Gap Tracker

Date opened: 2026-06-19
Owner: AT-0 / Beacon
Status: Active tracker

This is the living plan for closing Beacon's gap against current web-search and
browser-agent industry patterns. Update this file as each item moves from
planned to partial to complete.

Completion rule: mark an item `Complete` only after the relevant PR is merged,
deployed, and covered by post-deploy smoke or an equivalent production check.
Use `Partial` for code that exists but is not yet productized, deployed, or
visible to the user.

## Industry Patterns To Track

| Pattern | Industry Examples | What Good Looks Like |
|---|---|---|
| Answer engine UX | Perplexity, Perplexica/Vane | Fast cited answers, focus modes, source cards, session history, transparent confidence and limitations. |
| Deep research agent | LangChain Open Deep Research, report-generating agents | Plan, subquestions, parallel search/extract, critique, synthesis, structured report, exportable sources. |
| Agent search API | Tavily-style search/extract/crawl/research APIs | Reliable search, extraction, crawl, caching, indexing, low-latency retries, clear usage/cost telemetry. |
| Browser action agent | browser-use, agent-browser, computer-use style tools | Structured action space, element snapshots, click/type/fill primitives, recovery loops, strict approvals for risky actions. |
| Private metasearch | SearXNG-backed search stacks | Self-hosted/free metasearch before paid providers, privacy-preserving provider fanout, configurable result sources. |

References:

- Vane / Perplexica-style private answer engine:
  `https://github.com/ItzCrazyKns/Vane`
- LangChain deep research:
  `https://docs.langchain.com/oss/python/deepagents/deep-research`
- LangChain open deep research:
  `https://github.com/langchain-ai/open_deep_research`
- Tavily agent search API:
  `https://www.tavily.com/`
- browser-use:
  `https://github.com/browser-use/browser-use`
- Vercel agent-browser:
  `https://github.com/vercel-labs/agent-browser`
- OpenAI computer-use safety guidance:
  `https://developers.openai.com/api/docs/guides/tools-computer-use`

## Where Beacon Shines Today

| Strength | Status | Notes |
|---|---|---|
| Safety-first architecture | Complete | Browser work stays behind exact approval queue matching; raw web content is untrusted evidence. |
| Cost control | Complete | Official/free sources first, Brave as primary paid/free-ish search, Perplexity last with spend guards. |
| Provider health | Complete | Health surfaces provider state, budget caps, circuits, and fallback posture. |
| Evidence audit | Complete | Beacon stores requests, sources, evidence, tool events, quality metadata, and retention inventory. |
| Prompt-injection posture | Complete | Citation quality, sanitizer, source ranking, and untrusted-content boundaries are explicit. |
| Consumer policy lanes | Complete | Forge/Family/Financial consumer routes enforce sensitivity and tool limits. |
| Browser execution safety | Partial | Approved runner exists; #483 hardens action allowlists and per-action audit logs, but is not live until merged/deployed. |

## Where Beacon Fails Today

| Gap | Current Failure | Status | Close Criteria |
|---|---|---|---|
| Perplexity-class UX | Users do not yet get a polished answer-engine surface with focus modes, session history, source cards, confidence, and limitations in one place. | Not started | Beacon UI has search mode controls, source cards, history, confidence, warning chips, and deep research report rendering. |
| UX visibility into evidence | Source ranking exists, but the UI does not yet make "why this source" obvious enough. | Partial | UI shows source quality, official/primary/general badges, rejected-source reasons, freshness, and citation support status. |
| Private/free metasearch | No self-hosted SearXNG-style provider tier before Brave. | Partial | Gateway has SearXNG provider adapter, health, spend-free routing, tests, and smoke coverage. |
| Deep research productization | Contracts, planner, reports, and canaries exist, but the user flow is not yet a rich research cockpit. | Partial | UI shows plan, subquestions, progress, coverage warnings, report, source table, and export path. |
| Research benchmark breadth | Deterministic quality canaries exist, but not a broader industry-style benchmark suite with latency, cost, citation precision, and refusal quality. | Partial | Eval harness covers current facts, official docs, local/weather, shopping, adversarial pages, and insufficient-evidence refusal. |
| Durable web cache/index | Beacon stores evidence, but it does not yet have a Tavily-like reusable crawl/index/cache layer for speed and cost reduction. | Not started | Evidence cache has TTL, dedupe, reuse policy, optional embeddings/rerank index, and cache hit telemetry. |
| Browser action UX | Approvals show preview metadata, but not before/after screenshots or an action timeline that feels reviewable by a human. | Partial | Approvals UI shows action timeline, pre/post screenshots, host allowlist, risk labels, and one-click deny/approve. |
| Browser action capability | Browser execution remains observation-first. It does not yet support structured click flows such as reservation navigation. | Partial | Click-only v2 supports approved element snapshots, same-host navigation, no credentials, no purchases, screenshots before/after, and per-click audit. |
| MCP/tool ecosystem | Beacon is mostly internal Alpha routes, not a tool marketplace style integration layer. | Not started | Beacon exposes policy-scoped tool contracts for approved internal agents and optional MCP-facing consumers. |
| Product-mode defaults | Users cannot choose "official only", "news/current", "shopping", "academic", "local/weather", or "deep research" as first-class modes. | Not started | Mode selector maps to source policies, provider strategy, extraction budget, and UI labels. |
| Ops SLO dashboard | Health exists, but no one-page SLO dashboard for answer latency, cost, provider failures, citation quality, and browser approvals. | Partial | Health/observability page shows SLO cards, trend windows, and action items. |

## Closure Plan

| Priority | Workstream | Status | Acceptance Criteria |
|---:|---|---|---|
| 0 | Keep this tracker current | In progress | Every Beacon web-agent PR updates this file when it changes a tracked gap. |
| 1 | Merge/deploy #483 browser-action executor hardening | PR ready | Approved runner has strict same-host allowlist, caps, no forms/downloads/credentials, per-action audit, and post-deploy smoke. |
| 2 | Add SearXNG/free metasearch provider | In progress | Gateway search provider order becomes SearXNG -> Brave -> Perplexity, with health and smoke; specialized free APIs remain separate first-choice routes. |
| 3 | Beacon answer-engine UX v1 | Not started | UI has focus modes, source cards, history, confidence/limitations, and visible cost/provider state. |
| 4 | Evidence transparency UX | Not started | Users can inspect source quality, rejected-source reasons, freshness, official-host match, and claim support. |
| 5 | Eval harness v1 | Not started | CI or scheduled smoke runs a fixed benchmark set and records accuracy, citation quality, refusal quality, latency, and cost. |
| 6 | Deep research cockpit | Partial | UI renders research plan, subquestions, progress, warnings, final report, and exportable citations. |
| 7 | Cache/rerank/index layer | Not started | Beacon reuses recent fetch/extract evidence safely, records cache hits, and supports local reranking. |
| 8 | Browser approval UX v2 | Not started | Approvals page includes action timeline, before/after screenshots, host allowlist, and risk flags. |
| 9 | Browser click-only v2 | Not started | Structured clicks are approved per target, no typing, no credentials, no purchases, no cross-host jumps. |
| 10 | Ops/SLO dashboard | Not started | Health UI reports latency, cost, quality canary, provider state, browser approvals, and next operator action. |

## UX Improvement Notes

Beacon needs to feel less like an internal route and more like a trustworthy
research product. The first UX target is not decoration; it is operator
confidence.

Required UX surfaces:

- Search mode selector: `All`, `Official`, `News/current`, `Shopping`,
  `Academic`, `Local/weather`, `Deep research`.
- Answer header: selected mode, provider route, confidence, cost/spend status,
  and whether evidence is `supported`, `weak`, or `insufficient`.
- Source cards: source quality badge, official-host match, citation support,
  freshness, rejected-source reason when applicable.
- Research progress: visible subquestions, search/extract steps, coverage
  warnings, and why Beacon stopped.
- Approval review: browser action timeline, allowed host, blocked capabilities,
  screenshots required, approval hash prefix, and deny/approve controls.
- History: searchable prior Beacon asks with provider/cost/source metadata.
- Empty/error states: plain explanations for "no verified answer", provider
  capped, browser runtime disabled, and approval required.

## Current Next Step

Finish and merge the open browser-action executor PR plus the SearXNG provider
PR. Those are the safety and cost foundations for the next UX push.

After those are deployed, the next best production workstream is:

1. Beacon answer-engine UX v1.
2. Eval harness v1.
3. Evidence transparency UX.
