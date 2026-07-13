# ADR-0032: Approved Real Trace Sampling Boundary

Date: 2026-07-13

Status: Proposed

Related: Phase 25 Real Trace Sampling Workflow

## Context

Alpha's deterministic chat evals replay synthetic and manually redacted cases.
Real failure shapes improve those evals, but raw prompts, responses, memory,
identifiers, and tool context must not enter Git, logs, or long-lived runtime
storage.

The existing chat outcome endpoint is metadata-only. It is useful for score
calibration, but it intentionally cannot reconstruct a replay turn.

## Decision

Real trace sampling is an offline operator workflow in Alpha.

- The raw candidate file must remain outside the repository.
- The input carries a safe approval reference, an explicit approved status,
  confirmation that sensitive terms were reviewed, and a
  `delete_raw_after_export` retention policy.
- Preparation writes the exact redacted review artifact outside the repository.
  The operator reviews that artifact and records its SHA-256 digest in the
  approval record.
- Export requires both the approval reference and approved digest through the
  CLI, plus a detached Ed25519 operator signature over the canonical approval
  statement. It recomputes the redacted artifact and fails closed if the
  reference, digest, or signature does not match, binding approval to the exact
  content written to the corpus.
- Outcome metadata supplies route, quality, escalation, repair, memory budget,
  and prompt tool-policy expectations. Raw message and thread identifiers are
  not accepted as outcome fields.
- The exporter allowlists candidate fields, requires effective operator-provided
  redaction terms, generates pseudonymous trace and case IDs, redacts contact
  tokens and reviewed terms, rejects generic and provider-native credential
  formats, rejects duplicates, and writes the corpus atomically.
- The exporter emits a metadata-only batch manifest and never logs raw trace
  content. Successful export requires explicit deletion confirmation and removes
  both the raw source and reviewed artifact after the atomic corpus write.
- The existing deterministic eval harness remains the replay authority.
- The private approval key remains outside the repository and is never read by
  the exporter. The exporter receives only the detached signature and public
  key. Once a signed batch is committed, CI and runtime loaders receive the
  public-key path through `ALPHA_CHAT_TRACE_APPROVAL_PUBLIC_KEY_PATH`.

## Boundaries

- No automatic production trace capture.
- No raw trace database, API route, upload surface, or provider call.
- No claim that regex redaction is a complete DLP system. Human review of the
  exact digest-bound redacted artifact is part of the approval contract, and
  the exporter fails closed on fields or secret patterns it does not accept.
- Destructive cleanup requires the explicit `--delete-inputs-after-export`
  confirmation. Without it, export fails before writing or deleting anything;
  successful status is emitted only after both input artifacts are removed.
- Direct corpus edits cannot mint approval. Load-time validation recomputes the
  batch digest and verifies the detached signature against the configured
  public key.
- Every sampled case must appear in exactly one signed batch. The single
  pre-Phase-25 fixture is accepted only by its exact full-case digest; arbitrary
  unsigned cases cannot be added beside a valid batch.
- Sampled traces do not influence live Auto routing. Phase 26 owns that gate.

## Operator Workflow

1. Run `sample_chat_traces.py --prepare-review-output <outside-git-path>` and
   inspect every redacted field in the generated artifact.
2. Extract `approval_statement` byte-for-byte and sign it with the operator's
   Ed25519 private key using a trusted signer outside this repository.
3. Run the exporter with `--approval-ref`,
   `--approved-redacted-content-sha256`, `--approval-signature`, and
   `--approval-public-key` from that approved artifact and detached signature.
   Pass the exact `--review-artifact` and explicitly confirm
   `--delete-inputs-after-export`.
4. Confirm successful output reports both inputs deleted, retain only the
   reference/digest/signature evidence, run the deterministic eval gate, and
   submit the corpus diff through normal branch protection.

## Consequences

- Real failures can become regression fixtures without committing their raw
  transcript or stable identifiers.
- Every sampled batch has reviewable approval, approved-content digest,
  retention, count, and source-hash metadata.
- Operators must curate expectations; successful export enforces removal of the
  raw local source and redacted review artifact after recording their digest and
  detached signature.
- Before the first real batch is committed, the operator must provision an
  Ed25519 approval key outside Git and configure its public-key path in CI and
  the deployed Alpha environment.
