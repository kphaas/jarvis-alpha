# Beacon Agent

Beacon is the planned Alpha agent for public internet evidence gathering.

P6/P7 still keeps this package inert:

- no LaunchAgent;
- no scheduled runner;
- no browser execution;
- no memory ingest;
- no writes outside local planning/evidence contracts.

The active implementation lives in `brain.services.internet_scout`. Reviewed
Gateway search/fetch/extract/crawl egress, local-LLM citation envelopes, browser
approval queueing, and RLS evidence storage are available through the Brain
routes, but scheduled agent runtime behavior is deferred.
