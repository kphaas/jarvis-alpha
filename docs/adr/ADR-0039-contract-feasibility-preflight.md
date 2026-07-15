# ADR-0039: Contract Feasibility Preflight

Date: 2026-07-15

Status: Proposed

Related: Phase 29 Local Output Contract Hardening, Phase 30 Deterministic Local
Decoding, Phase 31 Contract-Failure Trace Expansion, Phase 32 Approved
Contract-Failure Batch Activation, Phase 33 Contract Feasibility Preflight

## Context

The first approved contract-failure trace exposed an impossible local output contract.
Its prompt required the term `purge` while the safe-recovery contract also forbade
`purge`. Alpha still called the initial model and one bounded repair before the quality
gateway rejected the answer. A stronger model cannot satisfy contradictory constraints,
so those calls add latency and cost without improving quality.

Feasibility must be decided from the model-agnostic compiled contract before any local,
cloud, Council, or repair call. The decision must remain deterministic, auditable, and
safe to persist without retaining the user's raw terms.

## Decision

- Add a versioned pure feasibility evaluator beside the existing output-contract
  compiler and validator.
- Mark a contract infeasible only when a mandatory required or ordered phrase
  necessarily contains a forbidden phrase. This matches the existing lexical
  substring validator and avoids speculative semantic contradiction detection.
- Run preflight before the initial Auto/Local call and before Council fan-out. An
  infeasible Council request skips both member calls and local synthesis.
- Recheck feasibility at the shared repair-loop boundary so direct callers cannot
  invoke the bounded retry for an impossible contract.
- Reuse the existing quality gateway and escalation ladder. The verification issue
  `output_contract_contract_infeasible` produces a conflict-specific safe response and
  operator review.
- Emit only schema version, feasible boolean, stable conflict codes, conflict count,
  and `allow_generation` or `skip_generation`. Do not log or persist conflicting terms.
- Keep feasible contracts on the existing generation, deterministic decoding,
  validation, normalization, repair, and gateway path unchanged.

```text
Compiled output contract
    -> deterministic feasibility check
        -> feasible: route -> validate -> bounded repair -> quality gate
        -> infeasible: zero model calls -> safe fallback -> operator review
```

## Four-Lens Rationale

- **Big Tech:** one provider-neutral preflight keeps policy outside adapters and applies
  identically to local and cloud-capable routes.
- **CIO:** impossible work consumes no provider spend and does not create vendor-specific
  behavior.
- **Big Finance:** reason-only metadata and operator review preserve an auditable,
  fail-closed decision without retaining prompt content.
- **Designer:** the response explains that the requirements conflict instead of
  incorrectly suggesting that a stronger model can solve them.

## Boundaries

- Phase 33 detects provable lexical conflicts only. It does not attempt semantic SAT
  solving, prompt rewriting, automatic priority selection, or model-based critique.
- Direct named cloud modes retain their existing output-contract behavior; this phase
  changes only the paths where Alpha already compiles and enforces a contract.
- Preflight does not mutate routing scores, benchmark evidence, memory, prompts, signed
  trace fixtures, or calibrated-routing rollout state.
- Council detail truthfully records zero executed member models when preflight blocks.

## Verification and Operations

1. Unit-test the approved Phase 32 redacted conflict and a non-conflicting substring
   boundary.
2. Prove the shared repair callback is not invoked for an infeasible contract.
3. Prove Local and Council streams make zero route calls, return the safe response, and
   persist feasibility, gateway, and operator-review metadata.
4. Keep the existing output-contract eval case count stable while reporting the Phase 33
   preflight result in daily trend evidence.

## Rollback

Revert the preflight evaluator and routing guard. No migration, secret, signed corpus,
provider configuration, or stored payload rewrite is required. Existing additive
metadata remains safe for older readers to ignore.

## Consequences

- Impossible contracts fail faster and more accurately with zero model cost.
- Lower-capability models spend their bounded repair attempt only on feasible failures.
- The conservative lexical check leaves semantic contradictions for future evidence-led
  phases rather than risking false-positive blocking now.
