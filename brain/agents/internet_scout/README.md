# Beacon Agent

Beacon is the planned Alpha agent for public internet evidence gathering.

P8/P9 still keeps this package inert:

- no LaunchAgent;
- no scheduled runner;
- no production browser runtime adapter;
- no memory ingest;
- no writes outside local planning/evidence contracts.

The active implementation lives in `brain.services.internet_scout`. Reviewed
Gateway search/fetch/extract/crawl egress, local-LLM citation envelopes, browser
approval queueing, approved-runner contracts, consumer-scoped integrations, and
RLS evidence storage are available through the Brain routes, but scheduled agent
runtime behavior is deferred.
