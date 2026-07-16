# ADR-0044: Targeted Missing-Term Repair

Date: 2026-07-16

Status: Proposed

Related: Phase 29 Local Output Contract Hardening, Phase 30 Deterministic Local
Decoding, Phase 38 Adversarial Assisted-Probe Expansion, Phase 39 Targeted
Missing-Term Repair

## Context

The deployed Phase 38 adversarial profile passed 18 of 24 task attempts on Brain.
Both failing analysis tasks were deterministic across three samples and reached the
existing single repair attempt, but the repaired answers still omitted specific
mandatory values. The one-sentence tradeoff omitted `97`; the dual-threshold answer
omitted `96`, `55`, and `local`.

The existing repair prompt repeated the full output contract. It did not identify
which required terms the validator found missing. Adding retries would increase
latency without making the same repair instruction more precise. Treating benchmark
contracts as signed user-output-contract traces would also misstate their provenance.

## Decision

- Reuse the validator's case-insensitive substring semantics to compute missing
  required terms from the failed response in memory.
- Add only those missing terms to a targeted checklist in the existing repair
  prompt. Keep the full output contract as the final authority.
- Pass the failed response to the shared renderer only for validation. Never copy it
  into the prompt, metadata, logs, benchmark result, or durable evidence.
- Keep the current one-repair limit, local route, deterministic generation policy,
  quality gateway, and operator escalation behavior unchanged.
- Apply the same shared behavior to production chat and the local benchmark runner.

```text
Failed response in memory
    -> output-contract validation
    -> exact missing-term set
    -> targeted checklist + full contract
    -> one existing local repair
    -> validation + quality gateway
    -> accept or fail closed
```

## Four-Lens Rationale

- **Big Tech:** one private helper keeps validation and repair selection on identical
  semantics instead of creating a second scoring system.
- **CIO:** the change adds no dependency, provider, route, model call, database, or
  operator surface.
- **Big Finance:** failed output and term values remain ephemeral; persisted metadata
  continues to contain only issue codes, hashes, counts, and decisions.
- **Designer:** Helm stays unchanged. Operators receive better local answers without
  another control or explanation panel.

## Boundaries

- This is lexical contract repair, not semantic self-critique or a learned policy.
- Required terms already originate from the in-memory output contract and are already
  present in the full contract instruction sent to the same model.
- No second repair, cloud fallback, routing-score mutation, raw capture, signed corpus
  activation, or paid egress is introduced.
- Benchmark evidence remains `assisted_probe` evidence and cannot be relabeled as a
  user-explicit output-contract trace.

## Verification

1. The targeted checklist contains only terms absent under validator semantics.
2. The failed response is not included in the repair prompt or result metadata.
3. Non-missing failures do not receive a targeted checklist.
4. Production and benchmark paths still stop after one repair attempt.
5. A deterministic benchmark regression repairs a known missing-value answer and
   retains only metadata-safe output.

Post-merge proof requires an exact-commit deploy and a three-sample Brain adversarial
run with the existing 48-call cap and external metadata-only output path.

## Rollback

Remove the optional failed-response input, targeted checklist helper, caller wiring,
and tests. The full-contract repair prompt and one-retry fail-closed behavior remain,
with no migration, secret rotation, evidence rewrite, or routing change.

## Consequences

- Lower-tier local models receive a precise correction signal without additional
  latency beyond an already-triggered repair.
- The next deployed adversarial run can determine whether targeted lexical repair
  closes the two reproducible Phase 38 gaps.
- Failures that remain after targeted repair identify a semantic planning gap rather
  than an ambiguous repair prompt.
