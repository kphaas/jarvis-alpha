# Beacon Production Readiness Runbook

Date: 2026-06-06

## Scope

Beacon is Alpha's internet evidence broker. Brain owns policy, evidence,
approval, and audit. Gateway owns public internet egress and provider
credentials.

This runbook covers the MVP production closeout for P13-P17:

- P13: health and readiness checks
- P14: provider reliability and fallback
- P15: audit and retention inventory
- P16: production agent wrapper
- P17: smoke and rollback

Longer-term industry gap closure is tracked in
`docs/state/BEACON_INDUSTRY_GAP_TRACKER.md`.

## Required Environment

Gateway:

- `GATEWAY_TOKEN` or service token accepted by Gateway
- Two search provider keys for production readiness:
  - `BRAVE_SEARCH_API_KEY` or `BRAVE_API_KEY`
  - `PERPLEXITY_API_KEY`
- `BEACON_MIN_USABLE_SEARCH_PROVIDERS=2` for redundant provider readiness
- Optional provider order: `BEACON_SEARCH_PROVIDER_ORDER=brave,perplexity`
- Provider spend guards:
  - `BEACON_BRAVE_DAILY_SEARCH_LIMIT=50`
  - `BEACON_BRAVE_MONTHLY_SEARCH_LIMIT=1000`
  - `BEACON_PERPLEXITY_DAILY_SEARCH_LIMIT=3`
  - `BEACON_PERPLEXITY_MONTHLY_SEARCH_LIMIT=25`
  - Optional usage ledger path:
    `BEACON_SEARCH_USAGE_DIR=~/jarvis/state/beacon-search-usage`

Brain browser runtime:

- `BEACON_BROWSER_RUNTIME=playwright`
- `BEACON_BROWSER_SCREENSHOT_DIR=<writable directory>`
- Playwright package version must match the runtime contract in code.

Retention inventory:

- `BEACON_EVIDENCE_RETENTION_DAYS`, default 90
- `BEACON_BROWSER_SCREENSHOT_RETENTION_DAYS`, default 30

Retention deletion:

- Default is safe inventory only.
- Actual deletion also requires:
  - admin scope on `POST /v1/internet-scout/retention/delete-expired`
  - request body `confirm: "delete_expired_beacon_evidence"`
  - `dry_run: false`
  - `BEACON_RETENTION_DELETE_ENABLED=true`
- Screenshot deletion only runs when `include_screenshots: true`.
- Do not enable deletion until the operator has reviewed the dry-run counts.

## Health Checks

Brain readiness:

```bash
python scripts/smoke_beacon_production.py --skip-agent
```

Direct endpoints:

```bash
curl -skS -H "Authorization: Bearer ${TOKEN}" \
  https://jarvis-brain.tail40ed36.ts.net:8186/v1/internet-scout/health

curl -skS -H "Authorization: Bearer ${TOKEN}" \
  https://jarvis-brain.tail40ed36.ts.net:8186/v1/internet-scout/retention/report
```

Expected:

- `/v1/internet-scout/health` returns `status: ok` before production enablement.
- `checks.database.ok` is true.
- `checks.gateway.metadata.provider_redundancy_ok` is true.
- `checks.gateway.metadata.usable_provider_count` is greater than or equal to
  `checks.gateway.metadata.required_provider_count`.
- `checks.browser_runtime.ok` is true when browser execution is expected.
- `retention.mode` is `report_only`.
- `checks.recent_evidence` is diagnostic. A recent failed request should be
  investigated, but it does not block readiness when the core dependency checks
  are healthy.
- `checks.recent_evidence.metadata.source_quality` reports recent
  `supported`, `weak`, and `insufficient` chat evidence events plus rejected
  citation and prompt-injection counts. These are diagnostics; repeated
  `insufficient` events indicate provider ranking or source-quality issues.
- `checks.recent_evidence.metadata.quality_canary` reports the last scheduled
  deterministic canary result when available.

Dry-run retention cleanup:

```bash
curl -skS -X POST -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  https://jarvis-brain.tail40ed36.ts.net:8186/v1/internet-scout/retention/delete-expired \
  -d '{"confirm":"delete_expired_beacon_evidence","dry_run":true,"include_screenshots":false}'
```

Run actual cleanup only after dry-run review and explicit env enablement:

```bash
BEACON_RETENTION_DELETE_ENABLED=true \
curl -skS -X POST -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  https://jarvis-brain.tail40ed36.ts.net:8186/v1/internet-scout/retention/delete-expired \
  -d '{"confirm":"delete_expired_beacon_evidence","dry_run":false,"include_screenshots":false}'
```

## Full Smoke

Run this after deploy and before calling the MVP ready:

```bash
python scripts/smoke_beacon_production.py
```

For production targets, the smoke script uses a target-side token by default:

```bash
python scripts/smoke_beacon_production.py \
  --token-ssh-target jarvisbrain@jarvis-brain.tail40ed36.ts.net
```

You can also provide an explicit token:

```bash
BEACON_SMOKE_TOKEN="<redacted>" python scripts/smoke_beacon_production.py
```

Expected:

- health status `ok`
- retention mode `report_only`
- agent status `completed`
- selected tool `search`
- `raw_web_content_is_untrusted` is true
- at least one citation when providers return usable search results
- source-quality status is `supported` or `weak` for normal sourced questions
- official docs/API queries cite an official host or return insufficient
  evidence instead of presenting weak sources as proof
- deterministic quality evals pass:
  `python scripts/eval_beacon_search_quality.py`
- committed contracts are current:
  `python scripts/export_beacon_contract_schema.py --check`

The smoke script does not print tokens or raw retrieved content.

## AT-0 MVP Front-Door Smoke

Run this after deploy to prove the user-facing Alpha chat endpoint reaches
Beacon and that browser-use work stays behind the operator approval queue:

```bash
python scripts/smoke_at0_mvp_user_paths.py
```

For production targets, the smoke script uses a target-side token by default:

```bash
python scripts/smoke_at0_mvp_user_paths.py \
  --token-ssh-target jarvisbrain@jarvis-brain.tail40ed36.ts.net
```

Expected:

- weather chat uses `web_search` and cites Open-Meteo evidence
- deep research chat uses `deep_research` with cited Beacon evidence
- raw web content remains marked untrusted
- automatic memory writes are blocked and memory promotion review is required
- browser-use requests create a pending `beacon_browser_use` T4 approval visible
  from `/v1/approvals/pending`

## Helm Ask Quality Canary Suite

Run this after the production smoke when Helm Ask or Beacon ranking changed:

```bash
python scripts/smoke_helm_ask_canary.py --suite
```

For production targets, the suite uses a target-side token by default:

```bash
python scripts/smoke_helm_ask_canary.py \
  --suite \
  --token-ssh-target jarvisbrain@jarvis-brain.tail40ed36.ts.net
```

Expected:

- each canary returns a streamed answer
- Helm Ask uses `deep_research`
- Beacon reports `supported` evidence
- at least one accepted citation is present
- the expected official host is present
- forbidden stale-memory hosts are absent
- raw web content remains marked untrusted
- synthesis behavior is `answer_with_citations`
- automatic memory writes are blocked and memory promotion review is required

Use the single-prompt canary for focused debugging:

```bash
python scripts/smoke_helm_ask_canary.py \
  --prompt "Find the official OpenAI API reference URL."
```

## Citation Quality

Beacon ranks citations before they enter the local-model prompt:

- `official`: inferred official host for the query, for example
  `platform.openai.com` for OpenAI API docs.
- `primary`: source with documentation/API/reference path but not an inferred
  official host.
- `trusted_secondary`: public institutional source such as `.gov` or `.edu`.
- `general`: ordinary public source.
- `low_confidence` or `rejected`: social/video/forum sources, empty snippets, or
  content with prompt-injection markers.

For official docs, API reference, SDK, release note, status, terms, or privacy
queries, Beacon requires inferred official hosts when possible. Non-matching
sources remain in stored evidence for audit, but they are excluded from prompt
context and counted in quality metadata.

Investigate when:

- `source_quality.insufficient` grows for common official-docs questions.
- `rejected_citation_count` spikes after provider or query changes.
- `prompt_injection_rejection_count` is non-zero for a new source family.

## Provider Reliability

Gateway provider selection is fail closed:

- Explicit provider requests require that provider key and an open circuit.
- `auto` uses configured provider order and skips open circuits.
- Each provider can be hard-capped with daily/monthly request limits. Gateway
  reserves a request before calling the paid provider, so exhausted providers
  are skipped in `auto` mode or return HTTP 429 when requested explicitly.
- Provider failures are recorded in memory and open a cooldown circuit after the
  configured failure threshold.
- If no configured provider is usable, search returns 503.

Useful knobs:

- `BEACON_SEARCH_PROVIDER_ORDER`
- `BEACON_SEARCH_CIRCUIT_WINDOW_SECONDS`
- `BEACON_SEARCH_CIRCUIT_FAILURE_THRESHOLD`
- `BEACON_SEARCH_CIRCUIT_COOLDOWN_SECONDS`
- `BEACON_BRAVE_DAILY_SEARCH_LIMIT`
- `BEACON_BRAVE_MONTHLY_SEARCH_LIMIT`
- `BEACON_PERPLEXITY_DAILY_SEARCH_LIMIT`
- `BEACON_PERPLEXITY_MONTHLY_SEARCH_LIMIT`
- `BEACON_SEARCH_USAGE_DIR`

## Agent Wrapper

Use:

```http
POST /v1/internet-scout/agent/run
```

The response always includes:

- selected tool
- status
- request id when audited
- citations
- confidence
- untrusted-content warnings
- not-verified notes

Browser-shaped requests return `approval_required`; they do not start browser
automation. Use the existing browser approval request and run-approved endpoints
for approved browser execution.

## Rollback

Application rollback:

1. Revert the PR that introduced the production closeout.
2. Restart Brain and Gateway with the previous release.
3. Re-run the previous Beacon smoke or health check.

Data rollback:

- No new tables or destructive migrations are introduced in P13-P17.
- Retention is report-only and does not delete evidence.
- Existing Beacon evidence and tool events remain append-only.

Provider rollback:

- Remove a provider key or remove it from `BEACON_SEARCH_PROVIDER_ORDER`.
- Gateway will fail closed if no usable provider remains.

Browser rollback:

- Set `BEACON_BROWSER_RUNTIME=disabled` or unset it.
- Browser run-approved requests will fail closed through the existing runtime
  guard.
