# ADR-0042: Historical-Raw Provenance Gate

Date: 2026-07-15

Status: Proposed

Related: Phase 25 Real Trace Sampling Workflow, Phase 31 Contract-Failure Trace
Expansion, Phase 35 Feasible Contract-Failure Corpus Expansion, Phase 36
Historical-Raw Feasible Failure Batch

## Context

Phase 35 activated one signed `assisted_probe` failure. It is valid evidence from a
controlled local-model run, but it is not evidence from an existing Alpha conversation.
The corpus accepted the `historical_raw` lane without requiring metadata that proves an
operator deliberately selected an existing turn. A future batch could therefore be
misclassified or could combine assisted and historical evidence under one approval.

On 2026-07-15, an operator-approved metadata-only query of `/v1/chat/outcomes` returned
zero outcome rows and zero eligible historical contract-failure candidates. No raw
prompt, response, memory, or conversation text was accessed. Alpha cannot truthfully
activate a historical batch until a genuine eligible failure exists.

## Decision

- Require every new `historical_raw` contract-failure candidate to carry the exact
  signed provenance fields:
  - `historical_source_system: alpha_chat_history`;
  - `historical_selection_method: operator_selected_existing_turn`;
  - `historical_operator_attested: true`.
- Forbid those fields on `assisted_probe` cases. Preserve existing legacy and assisted
  signed cases without changing their bytes, signatures, or evidence lane.
- Reject a review batch that mixes assisted and historical contract-failure lanes. Each
  evidence class receives a separate digest, approval, signature, and sampling batch.
- Add `--require-historical-raw` to preparation and export. The command fails before
  writing a review artifact or corpus update when no historical case is present.
- Include assisted and historical case counts in metadata-only operator summaries and
  carry the signed provenance fields into zero-call replay details.
- Do not activate a Phase 36 batch in this change. Activation requires a naturally
  occurring eligible failure and a separate operator-approved digest.

```text
Existing failed Alpha turn
    -> metadata-only eligibility discovery
    -> explicit raw-access approval
    -> operator selection and attestation
    -> historical-only redacted review artifact
    -> digest approval and detached signature
    -> signed corpus activation
    -> zero-call replay gate
```

## Four-Lens Rationale

- **Big Tech:** provenance is enforced at the existing ingestion boundary, where every
  sampler and corpus load already converges.
- **CIO:** the current sampler, signature, and replay modules are reused; no service,
  dependency, database, or provider-specific integration is added.
- **Big Finance:** assisted evidence cannot be represented as historical evidence, and
  one signed approval cannot silently authorize both evidence classes.
- **Designer:** review and export summaries state the evidence-lane counts directly,
  making an empty or mixed historical batch obvious before approval.

## Boundaries

- No runtime capture, conversation store, database query path, upload endpoint, cloud
  call, routing-score mutation, or active calibrated-routing change is added.
- Provenance attestation does not prove output quality. Feasibility, post-repair failure
  reproduction, redaction, digest review, signature validation, and replay remain
  separate mandatory gates.
- Raw prompts and responses remain outside Git and are deleted after successful export.
- The temporary authenticated discovery session is not persisted in corpus metadata.
- No historical source ID, user ID, conversation ID, prompt, or response is emitted in
  eval details.

## Verification

1. Reject historical candidates with missing or invalid provenance.
2. Reject historical provenance on assisted probes.
3. Reject mixed assisted and historical contract-failure batches.
4. Reject preparation and export with `--require-historical-raw` when the historical
   count is zero.
5. Load the existing three signed corpus cases unchanged.
6. Replay a test-only signed historical case and expose only its bounded provenance.

## Rollback

Revert the additive provenance fields, lane check, CLI flag, summary counts, and replay
details. No migration, secret rotation, runtime-data rewrite, or corpus-signature change
is required because this decision activates no new batch.

## Consequences

- Alpha is ready to ingest historical evidence without overstating assisted probes.
- Historical coverage remains zero until real evidence is separately approved.
- A historical batch requires more operator steps, but those steps preserve provenance,
  reviewability, and rollback at the actual trust boundary.
