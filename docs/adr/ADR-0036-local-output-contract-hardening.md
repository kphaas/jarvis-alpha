# ADR-0036: Harden Local Output with Explicit Contracts

Date: 2026-07-14

Status: Proposed

Related: Phase 19 Repair Loop, Phase 27 Per-Model Task Benchmarks, Phase 28
Benchmark Evidence Ingestion, Phase 29 Local Output Contract Hardening

## Context

The approved local benchmark showed instruction-compliance failures in exact JSON,
grounded evidence selection, privacy tradeoff coverage, and safe recovery ordering.
Replacing the model or adding a larger static system prompt would not address the
software boundary: Alpha needs to make explicit response requirements compilable,
verifiable, repairable once, and observable across model providers.

## Decision

Alpha adds a provider-neutral `chat_output_contract.v1` boundary beside the existing
verifier, repair loop, and quality gateway.

- Alpha compiles only explicit user constraints. Version 1 recognizes exact JSON keys,
  stated privacy dimensions, sentence limits, and safe recovery constraints.
- The initial local or Auto prompt receives a compact contract instruction. Explicit
  cloud selections keep their existing path.
- Validation is deterministic and returns stable issue codes. Contract terms and raw
  model text are not written to outcome metadata or logs.
- Before a model retry, Alpha safely canonicalizes an isolated fenced JSON object and
  merges sentence boundaries when an explicit sentence cap is the only style defect.
  It then reruns every required, forbidden, ordering, and schema check.
- A failed local contract may use the existing repair loop once. The retry receives the
  original request and evidence pack, never the untrusted prior response.
- A second failure is replaced by the quality gateway's safe fallback and escalates to
  operator review. The retry count cannot exceed one.
- Council synthesis uses the same contract because synthesis is local.
- `benchmark_local_output_contract.py` measures the assisted local path separately from
  the raw Phase 27 benchmark. It is dry-run by default, local-only, capped at eight calls,
  metadata-only, advisory, and ineligible for Phase 28 evidence ingestion or routing.
- Calibrated routing remains unchanged and default-off.

```text
Explicit user constraint
        -> contract compiler
        -> local prompt instruction
        -> deterministic validator
        -> one local repair at most
        -> quality gateway
        -> response or safe fallback
```

Provider-native structured-output APIs are intentionally not required. They can be used
inside future adapters as an optimization, but Alpha's validation remains the portable
source of truth.

## Operations

Plan the assisted benchmark with zero model calls:

```bash
python scripts/benchmark_local_output_contract.py
```

Run the four local tasks with a worst-case eight-call cap:

```bash
python scripts/benchmark_local_output_contract.py \
  --live \
  --max-calls 8 \
  --output /path/outside-git/local-output-contract-benchmark.json
```

The output must not be ingested as raw-model evidence. Compare it with the approved raw
local scorecard as a separate assisted-pipeline result.

## Rollout and Rollback

1. Deploy with calibrated routing off.
2. Confirm `/v1/chat/evals` includes a passing `output_contract` group.
3. Run the local-only assisted benchmark and compare quality and latency with the raw
   approved local benchmark.
4. Sample contract failures only through the existing signed, redacted trace workflow.

Rollback is code-only: remove contract compilation from the route and restore the prior
repair-loop call. There is no database migration, secret, evidence-corpus, or routing
policy change.

## Consequences

- Lower-tier models get explicit scaffolding and one bounded correction opportunity.
- The same validation behavior works across Ollama and cloud providers.
- Latency can increase by one local inference only when deterministic normalization
  cannot satisfy validation.
- Version 1 uses transparent structural and lexical checks. It does not prove semantic
  correctness, infer unstated requirements, or replace evidence verification.
