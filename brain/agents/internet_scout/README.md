# Beacon Agent

Beacon is the planned Alpha agent for public internet evidence gathering.

P10/P11 still keeps this package inert:

- no LaunchAgent;
- no scheduled runner;
- no autonomous browsing loop;
- no automatic memory ingest;
- no writes outside reviewed evidence and promotion contracts.

The active implementation lives in `brain.services.internet_scout`. Reviewed
Gateway search/fetch/extract/crawl egress, local-LLM citation envelopes, browser
approval queueing, approved-runner contracts, consumer-scoped integrations, RLS
evidence storage, reviewed memory-promotion records, and a fail-closed
Playwright adapter factory are available through the Brain routes.

Production runtime deployment remains a separate operational phase: install and
pin Playwright, provision browser binaries, configure screenshot storage, add
retention/alerting, and only then enable `BEACON_BROWSER_RUNTIME=playwright`.
