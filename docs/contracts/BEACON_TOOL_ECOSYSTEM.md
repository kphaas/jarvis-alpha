# Beacon Tool Ecosystem Contract

Status: Contract v1, internal Alpha routes first.

Beacon is the policy boundary for public internet evidence and browser-click
actions. MCP or agent-tool adapters must call Beacon through these contracts
rather than calling Gateway, browsers, or paid providers directly.

## Supported Tool Contracts

| Contract | Route | Purpose | Guardrail |
|---|---|---|---|
| Answer evidence | `POST /v1/internet-scout/local-llm/tool` | Returns a local-LLM-safe citation envelope. | Raw web content is evidence only, never instructions. |
| Streaming research | `POST /v1/internet-scout/local-llm/tool/stream` | Emits research progress and final cited answer payload. | Same policy as answer evidence. |
| Consumer lane | `POST /v1/internet-scout/consumers/{consumer}/local-llm/tool` | Applies Forge, Family, or Financial policy before research. | Consumer selects intent, Beacon owns sensitivity and tool limits. |
| Stored evidence | `GET /v1/internet-scout/requests/{request_id}` | Reads RLS-visible stored request evidence. | Raw query text is not stored; request shape and hashes are retained. |
| Saved history | `GET /v1/internet-scout/requests` | Lists searchable saved Beacon requests. | Search uses request metadata, source hosts/titles, claims, and event metadata. |
| Browser approval | `POST /v1/internet-scout/browser-task/approval-request` | Queues reviewed click-only browser work. | Human approval required before execution. |
| Browser execution | `POST /v1/internet-scout/browser-task/run-approved` | Runs one exact approved browser task. | Same-host allowlist, no forms, no typing, no credentials, timeout caps. |
| Browser audit history | `GET /v1/internet-scout/browser-task/history` | Reviews approval, run, and action audit events. | Append-only tool events under RLS. |
| Crawler scrape | `POST /v1/internet-scout/crawler/scrape` | Scrapes one public URL through cache-first Gateway egress. | Public URL safety, no browser runtime, raw content remains evidence only. |
| Crawler batch scrape | `POST /v1/internet-scout/crawler/batch-scrape` | Scrapes up to five public URLs through the same audited path. | Per-URL policy failures are returned as blocked items; no cap bypass. |
| Crawler map/crawl | `POST /v1/internet-scout/crawler/{map,crawl}` | Maps same-host links and bounded public pages. | Same-host crawl, 10 page cap, 2 depth cap, no forms or credentials. |
| Crawler extract | `POST /v1/internet-scout/crawler/extract` | Extracts simple schema fields with evidence spans. | Extraction is from scraped evidence; schemas do not become instructions. |
| Crawler render approval | `POST /v1/internet-scout/crawler/scrape/browser-approval-request` | Queues screenshot-backed browser render for hard pages. | Human approval required before browser runtime execution. |
| Crawler approved render | `POST /v1/internet-scout/crawler/scrape/browser-run-approved` | Runs an approved render and returns crawler-shaped evidence. | Existing approved queue row, screenshot required, audit and evidence links returned. |

## Consumer Policies

| Consumer | Sensitivity | Allowed tools |
|---|---|---|
| `forge` | `normal` | search, fetch, extract, crawl |
| `family` | `minor` | search, fetch, extract |
| `financial` | `financial` | search, fetch, extract |

Unsupported consumers fail closed with `consumer_not_supported`. Consumer routes
do not allow browser-use actions.

## MCP Adapter Rules

An MCP-facing adapter must preserve these boundaries:

1. Tool names map to the contracts above; no direct Gateway or browser runtime
   exposure.
2. Adapter input must fit the existing Pydantic request models.
3. Secrets and provider keys stay in env/secrets, never in MCP tool input or logs.
4. Browser actions remain approval-first and click-only unless a new reviewed
   contract is added.
5. Paid providers remain behind the free-source router, SearXNG, Brave, then
   Perplexity fallback with spend guards.
6. Saved history search must stay RLS-bound and must not require storing raw
   user query text.

## Crawler MCP Adapter v1

Machine-readable contract:
[`beacon_crawler_mcp_adapter.v1.json`](./beacon_crawler_mcp_adapter.v1.json).

The crawler MCP adapter is a translation layer, not a second crawler. It should
accept MCP tool calls, validate them against the JSON contract, then call the
existing Alpha HTTP route. Alpha keeps auth, scopes, policy, cache lookup,
Gateway egress, stored evidence, and audit writes.

| MCP tool | Alpha route | Approval posture |
|---|---|---|
| `beacon.crawler.scrape` | `POST /v1/internet-scout/crawler/scrape` | No approval; read-only public URL evidence. |
| `beacon.crawler.batch_scrape` | `POST /v1/internet-scout/crawler/batch-scrape` | No approval; capped at five URLs. |
| `beacon.crawler.map` | `POST /v1/internet-scout/crawler/map` | No approval; same-host, page/depth capped. |
| `beacon.crawler.crawl` | `POST /v1/internet-scout/crawler/crawl` | No approval; same-host, page/depth capped. |
| `beacon.crawler.extract` | `POST /v1/internet-scout/crawler/extract` | No approval; extracts from scraped evidence. |
| `beacon.crawler.render_approval_request` | `POST /v1/internet-scout/crawler/scrape/browser-approval-request` | Queues human approval. |
| `beacon.crawler.render_run_approved` | `POST /v1/internet-scout/crawler/scrape/browser-run-approved` | Requires an approved queue id. |

Render retry stays deferred. The current production rule is to keep watching
the Beacon Ops render-quality rollup and only add retry/tuning if weak or empty
renders, missing screenshots, or missing evidence cross the operator threshold.

## Disabled Runtime Skeleton

Alpha exposes a status-only runtime skeleton at
`GET /v1/security/mcp/adapters/beacon-crawler`. The skeleton is disabled by
default behind `BEACON_CRAWLER_MCP_ADAPTER_ENABLED`, and even when that env flag
is set it remains `blocked_unimplemented` until a reviewed invocation bridge is
added. This keeps MCP discovery visible without creating a new execution path,
egress path, or approval bypass.

## Current Non-Goals

- Public tool marketplace.
- Autonomous browsing loops.
- Credential entry, forms, purchases, sends, downloads, or cross-host browser
  action chains.
- Adding social, paid, or private-data connectors based only on source metadata.
