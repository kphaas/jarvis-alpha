# ADR-0027: Spark Target Memory Lane

Date: 2026-06-16

Status: Accepted

## Context

Spark already has reviewed principal-scoped personality memory for Ken-like
voice, boundaries, and preferences. That is not enough for reply drafting.

Reply quality also depends on who Ken is talking to and what is still open with
 that specific person. If Spark mixes recipient context into principal voice
 memory, the prompt becomes noisy and cross-person leakage becomes likely.

The operator also needs a safe way to turn selected thread context into durable
memory without storing raw thread bodies.

## Decision

Add a second reviewed Spark memory lane for the selected reply target.

- Principal personality memory stays separate and continues to shape voice.
- Target memory is scoped by `principal_id + target_ref_hash`.
- Target memory kinds are:
  - `open_loop`
  - `preference`
  - `profile_fact`
- Target memory proposals are created manually from the selected draft target
  and thread preview.
- Proposal records store only operator-authored summary text plus evidence
  hashes. They do not store raw message bodies.
- Approved target memory writes go through dedicated SECDEF functions and their
  own table, not `alpha_personality_memory`.
- Draft grounding may use only:
  - principal personality memory for voice
  - selected-target memory for the chosen recipient
- Target memory from one recipient must never be used for another recipient.
- Prompt preview and review UI must show why selected-target memory was used.

## Consequences

- Spark gets a tighter reply loop: preview thread, mark memory, review, approve,
  draft, then send.
- Cross-recipient leakage risk is lower because the target lane is explicit and
  hash-scoped.
- Open loops become first-class and can stay active until Ken archives them.
- Proposal review stays human-controlled and metadata-only.

## Non-Goals

- No automatic extraction from raw thread text in this batch.
- No auto-promotion from target memory into semantic memory.
- No cross-channel reuse of target memory outside the selected reply target.

## Verification

- Schema tests verify a dedicated target-memory table, SECDEF readers/writers,
  and forced RLS.
- Service tests verify proposal persistence uses evidence hashes only and
  prompt items prioritize active open loops.
- Route tests verify admin review routes, safe logs, and T2 route
  classification.
- UI tests verify the selected-target review flow, mark-for-memory action, and
  target-memory debug preview.
