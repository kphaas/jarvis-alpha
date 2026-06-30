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

## Consumer Policies

| Consumer | Sensitivity | Allowed tools |
|---|---|---|
| `forge` | `normal` | search, fetch, extract, crawl |
| `family` | `minor` | search, fetch, extract |
| `financial` | `financial` | search, fetch, extract |

Unsupported consumers fail closed with `consumer_not_supported`. Consumer routes
do not allow browser-use actions.

## MCP Adapter Rules

An MCP-facing adapter can be added later, but it must preserve these boundaries:

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

## Current Non-Goals

- Public tool marketplace.
- Autonomous browsing loops.
- Credential entry, forms, purchases, sends, downloads, or cross-host browser
  action chains.
- Adding social, paid, or private-data connectors based only on source metadata.
