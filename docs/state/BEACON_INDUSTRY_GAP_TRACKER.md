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
| Agent search API | Tavily-style search/extract/crawl/research APIs | Reliable search, scrape, map, extraction, crawl, caching, indexing, low-latency retries, clear usage/cost telemetry. |
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
| Cost control | Complete | Official/free sources first, SearXNG as free/private search, Brave second, Perplexity last with spend guards. |
| Provider health | Complete | Health surfaces provider state, budget caps, circuits, and fallback posture. |
| Evidence audit | Complete | Beacon stores requests, sources, evidence, tool events, quality metadata, and retention inventory. |
| Prompt-injection posture | Complete | Citation quality, sanitizer, source ranking, and untrusted-content boundaries are explicit. |
| Consumer policy lanes | Complete | Forge/Family/Financial consumer routes enforce sensitivity and tool limits. |
| Browser execution safety | Complete | Approved runner is deployed with same-host allowlists, timeout/step caps, no forms/downloads/credentials, and per-action audit logs. |

## Where Beacon Fails Today

| Gap | Current Failure | Status | Close Criteria |
|---|---|---|---|
| Perplexity-class UX | Beacon now has an answer-first workspace, compact saved-run history, and visible browser-request workflow, but the full operator cockpit is still maturing. | Partial | Beacon UI has search mode controls, answer workspace, source cards, history, confidence, warning chips, answer-quality score, evidence transparency, and deep research report rendering. |
| UX visibility into evidence | Source ranking, rejected-source reasons, freshness, official-host match, claim support, and compact answer-quality scoring are now visible in the Beacon UI. | Complete | UI shows source quality, official/primary/general badges, rejected-source reasons, freshness, citation support status, and answer-quality rollup after deployed smoke. |
| Private/free metasearch | Gateway now routes through self-hosted SearXNG before Brave and Perplexity. | Complete | Gateway has SearXNG provider adapter, health, spend-free routing, tests, and smoke coverage. |
| Deep research productization | Contracts, planner, reports, canaries, live step streaming, cockpit progress, redacted citation/evidence bundle metadata, and markdown/JSON export are visible in the Beacon UI. | Complete | UI shows plan, subquestions, progress, coverage warnings, report, source table, live trace, redaction metadata, and export path. |
| Research benchmark breadth | Deterministic quality canaries, answer-eval reporting, scheduled trend summaries, and compact Ops trend drilldown exist. | Complete | Eval harness covers current facts, official docs, local/weather, shopping, adversarial pages, insufficient-evidence refusal, answer-quality score regressions, latency, zero-spend cost posture, citation precision, 7-run scheduled trend summaries, and operator drilldown. |
| Durable web cache/index | Beacon has a DB-backed public-web evidence cache with TTL, URL dedupe, search-term GIN index, local quality/term rerank, hit telemetry, Ops status, and runtime extract reuse before Gateway calls. | Complete | Evidence cache has TTL, dedupe, reuse policy, optional embeddings/rerank index, and cache hit telemetry. |
| Crawler API | Beacon has deployed crawler scrape, batch scrape, map, crawl, schema extraction, approval-gated browser render, compact console controls, map/crawl stop summaries, crawler history, render quality metadata, and evidence export using existing Beacon evidence storage. | Complete | Crawler endpoints are merged, deployed, smoke-tested, visible in Beacon Ops, and usable from Beacon with cache status, blocked markers, crawl caps, render quality status, history, and evidence export. |
| Browser action UX | Approval payloads include v2 review metadata, and the Approvals UI now shows a compact review summary, action timeline, host allowlist, screenshot policy, risk labels, blocked capabilities, click targets, and the approve/deny decision boundary. | Complete | Approvals UI shows action timeline, pre/post screenshots, host allowlist, risk labels, and one-click deny/approve. |
| Browser action capability | Browser execution supports a bounded approved-selector click path, and crawler browser-render scrape requests now queue and run through the same approval boundary before returning screenshot-backed crawler evidence. | Partial | Click-only v2 supports approved element snapshots, same-host navigation, no credentials, no purchases, screenshots before/after, and per-click audit. |
| MCP/tool ecosystem | Beacon now has a documented internal tool ecosystem contract for policy-scoped consumers, but no public MCP server adapter yet. | Partial | Beacon exposes policy-scoped tool contracts for approved internal agents and optional MCP-facing consumers. |
| Product-mode defaults | Focus modes now expose source policy, provider strategy, extraction budget, page cap, and run labels in the Beacon UI, and the request body uses the selected mode cap. | Complete | Mode selector maps to source policies, provider strategy, extraction budget, and UI labels. |
| Ops SLO dashboard | Beacon now has a one-page Ops dashboard for answer latency, provider state, spend-guard posture, citation quality, browser approvals, and operator actions. | Complete | `/beacon/ops` shows SLO cards, 24h windows, provider/cost/citation/browser sections, and action chips after deployed smoke. |
| Crawler render-quality Ops | Beacon Ops now rolls up approved-render weak/empty rates, missing screenshots, missing evidence counts, and watch/action guidance without storing raw page content in audit metadata. | Complete | `/beacon/ops` shows render quality rates/counts from 24h browser-run audit events and says when to tune render retry/site extraction. |

## Closure Plan

| Priority | Workstream | Status | Acceptance Criteria |
|---:|---|---|---|
| 0 | Keep this tracker current | In progress | Every Beacon web-agent PR updates this file when it changes a tracked gap. |
| 1 | Merge/deploy #483 browser-action executor hardening | Complete | Approved runner has strict same-host allowlist, caps, no forms/downloads/credentials, per-action audit, and post-deploy smoke. |
| 2 | Add SearXNG/free metasearch provider | Complete | Gateway search provider order becomes SearXNG -> Brave -> Perplexity, with health and smoke; specialized free APIs remain separate first-choice routes. |
| 3 | Beacon answer-engine UX v1 | Partial | UI has focus modes, answer workspace, source cards, history, confidence/limitations, visible cost/provider state, answer-quality score, and evidence transparency. |
| 4 | Evidence transparency UX | Complete | Users can inspect source quality, rejected-source reasons, freshness, official-host match, claim support, and answer-quality rollup in the deployed Beacon UI. |
| 5 | Eval harness v1 | Complete | Scheduled canary status is surfaced through Beacon health and Helm summary; answer-quality scenarios cover strong vendor comparisons, missing official coverage, unsupported pricing refusal, and prompt-injection refusal; eval payload reports latency, zero-spend cost posture, planned budgets, citation precision, 7-run trend deltas, and compact Ops drilldown. |
| 6 | Deep research cockpit | Complete | UI renders research plan, subquestions, live progress, warnings, final report summary, ranked sources, markdown export, and redacted evidence-bundle export metadata. |
| 7 | Cache/rerank/index layer | Complete | Beacon stores recent public evidence snippets with TTL, URL dedupe, indexed search terms, local rerank metadata, cache-hit counters, Ops status, and runtime extract reuse. |
| 8 | Browser approval UX v2 | Complete | Approval contracts include action timeline, screenshot policy, host allowlist, URL hashes, risk labels, click targets, and deny/approve-compatible metadata rendered in a compact review UI. |
| 9 | Browser click-only v2 | Partial | Backend runner supports approved selectors, no typing, no credentials/forms/purchases, no cross-host jumps, screenshots before/after, per-click audit, and compact operator request preview. |
| 10 | Ops/SLO dashboard | Complete | Beacon Ops reports latency, cost guard, quality canary, provider state, browser approvals, and next operator action. |
| 11 | Crawler API | Complete | Beacon exposes scrape/map/crawl/extract over bounded Gateway egress, reuses durable cache, records audit events, and reports crawler health in Ops after deploy smoke. |
| 12 | Crawler browser-render execution bridge | Complete | Crawler render/screenshot scrape requests queue browser-use approval, then approved runs return crawler-shaped text/title/canonical URL/screenshot evidence with audit links. |
| 13 | Crawler map/history UX | Complete | Beacon crawler console shows why map/crawl stopped, groups discovered links by host, surfaces blocked/robots markers, searches recent crawler runs, and exports stored evidence JSON. |
| 14 | Crawler batch scrape v1 | Complete | Beacon exposes a capped, cache-first batch scrape endpoint, standard smoke coverage, compact console mode, per-URL status, and per-URL audit/evidence records. |
| 15 | Crawler render quality v2 | Complete | Approved render responses expose quality status, visible-text length, screenshot policy, evidence-source count, and compact operator reasons without logging raw page text. |
| 16 | Crawler render-quality Ops rollup | Complete | Beacon health, Helm summary, and `/beacon/ops` report weak/empty render rate, missing screenshots, missing evidence counts, and render retry/tuning watch guidance. |
| 17 | Async crawl jobs | Deferred | Build only after crawler telemetry shows repeated page/time cap pressure; Ops now reports cap-pressure count/rate and async-job recommendation status. |
| 18 | MCP adapter | Deferred | Keep the current internal tool contract until Beacon has a real external MCP client or cross-agent protocol requirement. |

## UX Improvement Notes

Beacon needs to feel less like an internal route and more like a trustworthy
research product. The first UX target is not decoration; it is operator
confidence.

Required UX surfaces:

- Search mode selector: `All`, `Official`, `News/current`, `Shopping`,
  `Academic`, `Local/weather`, `Deep research`.
- Answer header: selected mode, provider route, confidence, cost/spend status,
  whether evidence is `supported`, `weak`, or `insufficient`, and compact
  answer-quality score across diversity, official coverage, freshness, and
  rejected-risk count.
- Source cards: source quality badge, official-host match, citation support,
  freshness, rejected-source reason when applicable.
- Research progress: visible subquestions, search/extract steps, coverage
  warnings, export readiness, redaction metadata, and why Beacon stopped.
- Approval review: browser action timeline, allowed host, blocked capabilities,
  screenshots required, approval hash prefix, and deny/approve controls.
- History: searchable prior Beacon asks with source/event metadata, and future provider/cost metadata when recorded.
- Empty/error states: plain explanations for "no verified answer", provider
  capped, browser runtime disabled, and approval required.

## Current Next Step

Beacon answer-engine UX v1, evidence transparency, provider telemetry, SearXNG,
and approved browser-action execution are deployed. The remaining work is now
operator depth rather than basic answer visibility.

The next best production workstream is:

1. Watch crawler cap telemetry in Beacon Ops; add async crawl jobs only after the async-job recommendation flips from `not_needed/watch` to `recommended`.
2. Keep the internal Beacon tool contract for now; build a real MCP adapter only when an external MCP client needs it.
3. Use the render-quality Ops watch/action status to decide whether render retries, site-specific extraction tuning, or screenshot-store alerts are warranted.
