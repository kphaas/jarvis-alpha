# ADR-0034: Add Advisory Per-Model Task Benchmarks

Date: 2026-07-14

Status: Proposed

Related: Phase 16 Model Capability Registry, Phase 26 Calibrated Routing Rollout Gate, Phase 27 Per-Model Task Benchmarks

## Context

Alpha has versioned static model capabilities and bounded outcome-calibrated routing,
but it does not yet compare every registered model on the same task classes. Outcome
metadata reflects production traffic mix, so it cannot by itself distinguish model
quality from task selection, evidence availability, or user behavior.

A benchmark lane must be reproducible and model-agnostic without adding paid calls to
every pull request or allowing benchmark output to silently rewrite live routing.

## Decision

Alpha defines one versioned synthetic task for each routing class: `fast`, `grounded`,
`analysis`, and `deep`.

- Every registered route runs the same task version and objective rubric.
- The capability registry records the configured provider model ID and advances to
  `chat_model_capability_registry.v2`.
- Rubrics score exact JSON, required evidence, bounded tradeoff reasoning, and ordered
  safe-recovery constraints. Check IDs and weights are visible; expected terms and raw
  responses are not emitted.
- Results include model ID, route, task class, score, registry score delta, latency,
  response length, and response SHA-256 only.
- Benchmark results are advisory. They never mutate model capability scores or Phase 26
  calibrated-routing inputs.
- `scripts/benchmark_chat_models.py` is dry-run by default and reports zero model calls.
- Live execution requires explicit `--live` and `--models`, is sequential, and is
  limited by `--max-calls` (default 4, maximum 64).
- Brokered/cloud routes additionally require `--allow-paid-models`.
- Adapter exceptions and provider errors become generic error codes; provider error
  text is not retained or logged.
- Required CI/deploy evals validate the task/rubric contract with reference responses
  and continue to make zero model calls.

This v1 benchmark measures objective instruction and supplied-fact compliance. It is
not a judge-model evaluation and does not claim to measure writing style, creativity,
or open-ended correctness.

## Commands

Plan the full matrix without model calls:

```bash
python scripts/benchmark_chat_models.py
```

Run the four local tasks with a four-call cap:

```bash
python scripts/benchmark_chat_models.py \
  --live \
  --models local \
  --max-calls 4
```

Run an explicitly approved paid comparison:

```bash
python scripts/benchmark_chat_models.py \
  --live \
  --models claude gemini \
  --allow-paid-models \
  --max-calls 8 \
  --output /path/outside-git/chat-model-benchmark.json
```

## Rollout

1. Merge and deploy the benchmark contract with no live calls.
2. Run the local lane and inspect failures before spending on cloud comparisons.
3. Obtain explicit operator approval for a bounded paid run.
4. Compare task scores, latency, cost tier, deployment, and privacy tier.
5. Keep Phase 26 in `off` or `shadow`; benchmark output is not routing evidence until a
   separate ingestion and approval design is reviewed.

Rollback is code-only: remove the benchmark script/eval group and return the capability
registry version to the prior implementation. No database, secret, or runtime policy
migration is involved.

## Consequences

- Lower and frontier models can be compared on identical reviewed tasks.
- CI proves the scorer and privacy contract without cost or provider availability.
- Live runs have explicit cost and call-count boundaries.
- Keyword and structure checks are transparent but shallow; task/rubric version changes
  require a new benchmark version rather than editing historical meaning in place.
- Configured model IDs improve provenance, but mutable provider aliases or local Ollama
  tags still require runtime digest capture in a future evidence-ingestion phase.
