# ADR-0045: Structured Constraint Finalizer

Date: 2026-07-16

Status: Proposed

Related: Phase 29 Local Output Contract Hardening, Phase 30 Deterministic Local
Decoding, Phase 39 Targeted Missing-Term Repair, Phase 40 Structured Constraint
Finalizer

## Context

The deployed Phase 39 adversarial run still passed 18 of 24 attempts. Targeted
repair improved one analysis task from score 40 to 80, but the local model still
omitted one validator-required value in each failing answer: `97` in the
one-sentence reliability tradeoff and `local` in the dual-threshold privacy check.

Another model retry would repeat a failed instruction while adding latency. A
general text synthesizer would be unsafe because lexical benchmark requirements do
not prove that Alpha can author arbitrary missing claims.

## Decision

- Add provider-neutral typed constraint slots to in-memory output contracts. Each
  slot binds an identifier, required terms, and a reviewed render clause.
- Run the finalizer only after the existing single local repair fails.
- Permit completion only when exactly one typed slot is missing, the contract is
  feasible, the response is non-empty, and the contract is not exact JSON.
- Append the reviewed clause, reuse existing sentence normalization, and accept the
  result only when the full output contract and evidence verification pass.
- Type slots only for explicit privacy-tradeoff contracts and reviewed analysis
  benchmark checks. Do not infer slots for arbitrary required terms.
- Record only action, reason, boolean, and count metadata. Keep slot values and raw
  responses out of logs and durable benchmark output.
- Bump local output benchmark results to schema v3 so finalized outputs are
  distinguishable from pure model output.

```text
One failed local repair
    -> identify exactly one missing typed slot
    -> append reviewed render clause
    -> preserve sentence limit
    -> full contract + evidence verification
    -> accept or fail closed
```

## Four-Lens Rationale

- **Big Tech:** typed contracts and shared validation avoid provider-specific prompt
  tricks and keep production and benchmark behavior aligned.
- **CIO:** deterministic completion adds no provider, dependency, or model call.
- **Big Finance:** the finalizer cannot invent untyped content, and persisted evidence
  identifies system assistance without retaining term values.
- **Designer:** concise constraints are completed without adding another Helm control
  or exposing internal repair text.

## Boundaries

- This is not semantic planning, open-ended reflection, or whole-answer generation.
- Exact JSON, multiple missing slots, infeasible contracts, forbidden content, and
  any remaining non-slot violation fail closed.
- No route, calibrated score, signed corpus, approval policy, cloud fallback, or paid
  egress changes.
- Benchmark evidence that used the finalizer is system-assisted output and must not
  be represented as unaided model capability.

## Verification

1. The two exact Phase 39 failure shapes pass after one deterministic finalization.
2. The finalizer adds no model calls and preserves the one-repair limit.
3. Multiple missing slots, incomplete render clauses, exact JSON, and unsafe content
   remain blocked.
4. Sentence limits and the complete output contract are revalidated after completion.
5. Production repair metadata and benchmark reports contain no slot values or raw
   responses.

Post-merge proof requires an exact-commit deploy and a three-sample Brain adversarial
run with the existing 48-call cap and an external metadata-only output path.

## Rollback

Remove constraint slots, the finalizer call after failed repair, benchmark v3 fields,
and their tests. The deployed Phase 39 targeted one-repair path remains unchanged.
No migration, secret rotation, evidence rewrite, or routing rollback is required.

## Consequences

- Reviewed single-slot omissions can close without another model call.
- Operators and evals can separate model-only success from system-assisted success.
- Multi-slot or semantic failures continue to escalate instead of being synthesized.
