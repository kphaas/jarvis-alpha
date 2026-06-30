# Beacon Internet Scout

Beacon is Alpha's read-only internet evidence broker. It lets local LLM flows
ask for public evidence without giving raw web pages authority over JARVIS
tools, memory, approvals, or secrets.

## Status

P10/P11:

- ADR and service contracts exist.
- Policy, URL/content safety, sanitizer, evidence, and planning helpers exist.
- Gateway search/fetch/extract/crawl endpoints are implemented.
- Current local weather queries route through Gateway's free Open-Meteo adapter
  before paid search providers.
- Gateway search can route through a configured SearXNG base URL before Brave
  and Perplexity, keeping private/free metasearch ahead of paid providers.
- Brain calls Gateway through `call_gateway_proxy()` only.
- `/v1/internet-scout/research` stores structured evidence under RLS.
- `/v1/internet-scout/local-llm/tool` returns a citation envelope for local
  model answer synthesis.
- `/v1/internet-scout/consumers/{consumer}/local-llm/tool` applies Forge,
  Family, and Financial consumer policy before returning a local-LLM envelope.
- `/v1/internet-scout/requests/{request_id}` returns RLS-visible stored evidence.
- Browser-use approval requests can be queued and an approved-runner route can
  verify and consume the exact approval row.
- Browser runs have an hourly operator quota, same-host observation checks,
  strict same-host network allowlists, screenshot review markers,
  content-addressed screenshot storage, no-download/no-form/no-credential-entry
  enforcement, timeout/step caps, and append-only per-action audit events.
- Approved browser runs can execute a bounded click-only plan using reviewed
  selectors: no typing, forms, credentials, risky purchase/send/submit targets,
  downloads, or cross-host navigation.
- The browser runner is adapter-based and fails closed unless
  `BEACON_BROWSER_RUNTIME=playwright` is configured with the reviewed runtime
  settings.
- Reviewed Beacon evidence can be promoted into semantic memory only through
  `/v1/internet-scout/requests/{request_id}/memory-promotions` and
  `/v1/internet-scout/memory-promotions/{promotion_id}/review`.
- No scheduler, autonomous browsing loop, or outbound action is wired.

## Placement

Brain owns policy, evidence contracts, and approval classification. Gateway must
own public egress. This preserves the existing Alpha invariant that Brain does
not call public internet hosts directly.

## Product Name

User-facing name: Beacon.

Code package: `brain.services.internet_scout`, kept descriptive so other Alpha
services can depend on the contracts without depending on brand language.

## Deferred Work

- P12: production deployment wiring for the Playwright runtime, including
  package installation, browser binary provisioning, LaunchAgent configuration,
  screenshot retention policy, and operational alerts.
- Future: scheduled Beacon agent behavior, multi-step action planning, and any
  browser-use flow involving T5 privacy/legal/financial/minor data.

## Browser Runtime Configuration

The default runtime is disabled. To enable the production adapter in a reviewed
deployment, set:

- `BEACON_BROWSER_RUNTIME=playwright`
- `BEACON_BROWSER_SCREENSHOT_DIR=<local private screenshot path>`
- `BEACON_BROWSER_PLAYWRIGHT_VERSION=1.49.1`
- `BEACON_BROWSER_TIMEOUT_MS=20000` unless a smaller reviewed value is needed
- `BEACON_BROWSER_MAX_STEPS=5` maximum; lower values are allowed
- `BEACON_BROWSER_MAX_RUNS_PER_HOUR=3` unless the operator approves a higher
  bounded limit
