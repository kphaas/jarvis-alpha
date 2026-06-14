# ADR-0025: Memory 2.0 Dream Consolidation Boundary

Date: 2026-06-14

Status: Accepted for P0/P2 scaffold

## Context

JARVIS already has working, episodic, semantic, Spark personality, Buddy, and
Dream Mode pieces. The missing architecture link is sleep-time consolidation:
reviewing memory after the fact to identify what should be promoted, merged,
decayed, or moved into a future procedural tier.

The risk is that memory consolidation can silently rewrite the operator model.
That makes naive automatic promotion unsafe, especially for identity,
relationship, child, legal, medical, and procedural facts.

## Decision

Add a read-only Dream consolidation planner before enabling any memory writes.

- Buddy remains the cheap synchronous janitor: caps, expiry alerts, watchdogs,
  and daily backlog summaries.
- Dream owns asynchronous reflection: promotion, dedupe, decay, and procedural
  candidate planning.
- This slice only emits reviewed candidates. It does not promote, merge, delete,
  decay, or create procedural memory rows.
- Candidate reports include counts and review-required flags. Buddy summaries
  are count-only and do not include raw memory text.
- Suspicious content that looks like prompt injection or secrets is blocked from
  candidate lists and counted separately.

## Consequences

This gives Spark, Ask, Chat, Buddy, and Dream a shared direction without adding
an unsafe write path. The next gated step can add reviewed SECDEF write
functions for specific actions:

- episodic or working to semantic promotion
- semantic duplicate merge
- reviewed decay or archival
- procedural memory extraction

## Non-Goals

- No graph memory in this slice.
- No Obsidian ingest in this slice.
- No automatic consolidation writes in this slice.
- No cross-principal graph traversal in this slice.

## Verification

- Unit tests cover promotion, duplicate, decay, procedural, and blocked
  candidate detection.
- Unit tests verify Buddy-safe summary text does not leak raw memory.
- Dream worker registration includes the consolidation activity.
- P0 hygiene tests confirm dead promotion constants are removed from
  `MemoryService` and vector dimensions remain explicit by domain.
