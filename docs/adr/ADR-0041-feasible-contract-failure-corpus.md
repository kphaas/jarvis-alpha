# ADR-0041: Feasible Contract-Failure Corpus Expansion

Date: 2026-07-15

Status: Proposed

Related: Phase 31 Contract-Failure Trace Expansion, Phase 32 Approved Batch
Activation, Phase 33 Contract Feasibility Preflight, Phase 35 Feasible
Contract-Failure Corpus Expansion

## Context

Alpha can replay signed redacted local output-contract failures, but its first approved
case compiles to an impossible contract and is now stopped by Phase 33 before model
generation. That case remains useful preflight evidence, but it cannot measure whether a
lower-capability model fails a valid contract after one bounded repair.

The corpus also did not distinguish operator-selected historical traces from controlled
local probes. Combining those evidence classes would overstate production coverage.

One controlled Phase 35 probe exposed two evidence-path consistency defects:

- a failed repair returned the original text while recording the retry evaluation;
- contact-token validation scanned metadata hashes as user text and could classify ten
  consecutive digits inside a SHA-256 digest as a phone number.

## Decision

- Keep `output_contract_failure` as the trace kind and extend new sampled cases
  additively with:
  - `expected_output_contract_feasible: true`;
  - `evidence_lane: assisted_probe | historical_raw`.
- Require all Phase 33 feasibility metadata on new contract-failure candidates. The
  candidate must report `allow_generation`, zero conflicts, and a feasible contract.
- Recompile the redacted prompt and reject it before review unless deterministic
  feasibility evaluation also returns feasible.
- Preserve the existing signed case byte-for-byte. Cases created before Phase 35 load
  as `legacy_unclassified`; Alpha does not infer provenance retroactively.
- Keep evidence lanes distinct in replay output. Assisted probes are real local-model
  outputs from controlled non-sensitive prompts, not claims about production traffic.
- On a failed bounded repair, keep the retry text, verification, and output-contract
  evaluation aligned. The quality gateway still replaces invalid output with the same
  safe fallback and requires operator review.
- Revalidate contact tokens only in content-bearing trace text fields. Safe metadata
  fields retain their existing allowlists, secret patterns, identifier checks, size
  bounds, and signed-digest protection.
- Report both total contract-failure count and feasible contract-failure count during
  review preparation and export.

```text
Controlled or operator-selected failure
    -> explicit evidence lane
    -> Phase 33 metadata check
    -> deterministic feasibility recompilation
    -> post-repair failure reproduction
    -> deterministic redaction
    -> operator digest approval
    -> Ed25519-signed corpus activation
    -> zero-call replay gate
```

## Four-Lens Rationale

- **Big Tech:** feasibility is checked at the ingestion boundary with the same portable
  compiler used by runtime; routing and provider adapters remain unchanged.
- **CIO:** the additive corpus v1 shape stays provider-neutral and introduces no new
  service or dependency.
- **Big Finance:** evidence provenance is signed, raw/review inputs remain outside Git
  and are deleted after export, and Codex cannot self-approve a batch.
- **Designer:** operator summaries show exactly how many cases are feasible failures and
  which evidence lane they represent.

## Boundaries

- No automatic production capture, database query, upload route, cloud call, model
  selection, routing-score mutation, or active calibrated-routing change is added.
- Assisted probes use controlled non-sensitive prompts. They do not substitute for a
  future operator-approved `historical_raw` batch.
- Raw prompts and responses remain outside Git and are not written to logs or eval
  payloads.
- The existing infeasible signed case is not relabeled, resigned, or deleted.
- Preparing a digest does not authorize signing or activation.

## Verification

1. Reject missing, false, conflicting, or mismatched Phase 33 feasibility metadata.
2. Reject an infeasible redacted prompt even if candidate metadata claims feasibility.
3. Preserve legacy signed-corpus loading without changing its digest.
4. Prove failed retry text and issue metadata stay aligned through the quality fallback.
5. Prove digit runs inside metadata hashes do not bypass text-field contact validation.
6. Replay every activated case through contract evaluation, quality gateway, and
   escalation with zero model calls.

## Rollback

Revert the additive fields, sampler checks, replay details, and failed-retry alignment.
Do not edit an already signed corpus batch in place; revert the whole activated batch
and its approval metadata together. No migration, secret rotation, model change, or
stored runtime-data rewrite is required.

## Consequences

- Feasible local failures can become durable evidence without being confused with
  impossible contracts or production traces.
- Failed retries remain fail-closed while producing internally consistent evidence.
- Historical coverage remains an explicit future collection task rather than an
  inference from assisted probes.
