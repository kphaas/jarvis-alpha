# Beacon Agent

Beacon is the planned Alpha agent for public internet evidence gathering.

P2/P3 still keeps this package inert:

- no LaunchAgent;
- no scheduled runner;
- no crawl/browser execution;
- no memory ingest;
- no writes outside local planning/evidence contracts.

The active implementation lives in `brain.services.internet_scout`. Reviewed
Gateway search/fetch egress and RLS evidence storage are available through the
Brain route, but scheduled agent runtime behavior is deferred.
