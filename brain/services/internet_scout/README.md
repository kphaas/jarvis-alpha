# Beacon Internet Scout

Beacon is Alpha's read-only internet evidence broker. It lets local LLM flows
ask for public evidence without giving raw web pages authority over JARVIS
tools, memory, approvals, or secrets.

## Status

P8/P9:

- ADR and service contracts exist.
- Policy, URL/content safety, sanitizer, evidence, and planning helpers exist.
- Gateway search/fetch/extract/crawl endpoints are implemented.
- Brain calls Gateway through `call_gateway_proxy()` only.
- `/v1/internet-scout/research` stores structured evidence under RLS.
- `/v1/internet-scout/local-llm/tool` returns a citation envelope for local
  model answer synthesis.
- `/v1/internet-scout/consumers/{consumer}/local-llm/tool` applies Forge,
  Family, and Financial consumer policy before returning a local-LLM envelope.
- `/v1/internet-scout/requests/{request_id}` returns RLS-visible stored evidence.
- Browser-use approval requests can be queued and an approved-runner route can
  verify and consume the exact approval row.
- The browser runner is adapter-based and fails closed unless a reviewed
  browser runtime is injected.
- No memory ingest, scheduler, or outbound action is wired.

## Placement

Brain owns policy, evidence contracts, and approval classification. Gateway must
own public egress. This preserves the existing Alpha invariant that Brain does
not call public internet hosts directly.

## Product Name

User-facing name: Beacon.

Code package: `brain.services.internet_scout`, kept descriptive so other Alpha
services can depend on the contracts without depending on brand language.

## Deferred Work

- P10: reviewed evidence promotion into memory/RAG, if approved.
- P11: production browser runtime adapter with dependency pinning, host
  sandboxing, screenshot storage, and operational run limits.
