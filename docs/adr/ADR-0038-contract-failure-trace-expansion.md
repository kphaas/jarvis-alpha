# ADR-0038: Contract-Failure Trace Expansion

Date: 2026-07-15

Status: Proposed

Related: Phase 25 Real Trace Sampling Workflow, Phase 29 Local Output Contract
Hardening, Phase 30 Deterministic Local Decoding, Phase 31 Contract-Failure
Trace Expansion

## Context

Alpha can already export operator-approved redacted traces and replay strategy,
memory, prompt, verification, repair, quality, and escalation metadata. The replay
path did not compile or evaluate Phase 29 output contracts, so an approved lower-model
contract failure could be stored only as a generic trace. That would not prove that the
portable validator still detects the failure or that the quality gateway still fails
closed.

The trace sampler must retain enough reviewed evidence to reproduce a contract failure
without adding automatic production capture, storing raw transcripts, invoking a model,
or weakening the existing detached-signature boundary.

## Decision

- Extend the existing `chat_redacted_trace_corpus.v1` case additively with an
  `output_contract_failure` trace kind. Existing unsigned legacy fixtures and signed
  generic batches remain byte-for-byte compatible.
- A contract-failure trace represents the final local response after the one bounded
  repair attempt failed. Its replay stage is explicitly `post_repair`; replay does not
  claim to rerun the historical model call.
- Candidate outcome metadata must prove that an output contract was applied and failed,
  the route was local, the repair action was `retry_local_once`, no repair succeeded,
  the quality gateway replaced the answer, and escalation required operator review.
- Preparation compiles the contract again from the redacted prompt and evaluates the
  exact redacted post-repair response. The contract ID and stable issue codes must match
  the candidate outcome before an operator can review or sign the artifact.
- The existing Ed25519 statement continues to bind the approval reference to the full
  canonical redacted cases. Contract kind, replay stage, expectations, response, and
  redaction metadata are therefore covered by the same digest and signature.
- Eval replay applies the same model-agnostic contract compiler, evaluator, verification
  adapter, quality gateway, and escalation ladder used by chat. Eval output contains only
  trace kind, stable issue codes, decisions, hashes, and policy versions.
- The sampler reports contract-failure counts during preparation and export. It does not
  emit prompts, responses, reviewed terms, or signatures to logs.

```text
External failed trace
    -> deterministic redaction
    -> contract failure reproduced
    -> exact artifact reviewed
    -> digest signed by operator
    -> corpus export + raw cleanup
    -> offline contract/gateway/escalation replay
```

## Boundaries

- No raw prompt, response, memory, contact token, identifier, credential, or private key
  enters Git or eval output.
- No automatic trace collection, runtime database, upload route, provider call, or live
  routing mutation is added.
- A post-repair trace proves that the final failed output is still rejected. It does not
  reproduce the historical model retry because raw retry prompts and intermediate model
  output are intentionally not retained.
- Generic traces cannot carry output-contract metadata. Contract-failure traces cannot
  omit or contradict their failed repair, fallback, escalation, contract ID, or issue
  expectations.
- Redaction that changes the contract or its reproduced issue set fails preparation. The
  operator approves only the exact redacted artifact that the eval will load.
- The private approval key remains outside Git and the exporter. Preparing a review
  artifact does not authorize Codex or CI to sign it.

## Operations

1. Build a candidate outside Git from an operator-selected local contract failure.
2. Set `trace_kind` to `output_contract_failure` and include the compact Phase 29 outcome
   fields, including contract ID and stable issue codes.
3. Prepare the redacted review artifact with `sample_chat_traces.py` and confirm its
   `contract_failure_case_count` and exact digest.
4. Review the redacted artifact, then explicitly approve its digest before signing the
   canonical statement with the Air-held Ed25519 private key.
5. Export with the detached signature, public key, and delete confirmation; run the
   deterministic eval gate before submitting the corpus diff.

## Rollout and Rollback

1. Deploy schema validation and replay support before exporting the first Phase 31 batch.
2. Keep calibrated routing off; contract-failure cases remain offline eval evidence.
3. Require the redacted corpus eval group to pass in CI and deploy gates.
4. Revert the additive case fields and replay branch to roll back. Existing corpus data,
   signing keys, runtime configuration, and database state require no rollback.

## Consequences

- Real lower-model contract failures can become durable regression tests without storing
  their raw turns or stable identifiers.
- Tampering with failure classification or expected issues invalidates the signed digest.
- Operators must still curate a real failed case and approve its exact redacted digest;
  implementation tests cannot substitute for that evidence.
- Replay remains zero-call, deterministic, metadata-only, and unable to affect Auto.
