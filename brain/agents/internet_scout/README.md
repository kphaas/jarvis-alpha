# Beacon Agent

Beacon is the planned Alpha agent for public internet evidence gathering.

P1 intentionally keeps this package inert:

- no LaunchAgent;
- no scheduled runner;
- no search/fetch/crawl/browser execution;
- no memory ingest;
- no writes outside local planning/evidence contracts.

The active implementation lives in `brain.services.internet_scout` until later
phases add reviewed Gateway egress and approval-gated runtime behavior.
