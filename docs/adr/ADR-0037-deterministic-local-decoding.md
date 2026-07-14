# ADR-0037: Deterministic Local Decoding

Date: 2026-07-14

Status: Proposed

Related: Phase 29 Local Output Contract Hardening, Phase 30 Deterministic Local
Decoding

## Context

Phase 29 proved that Alpha can compile, validate, repair, and fail closed on explicit
output contracts. Post-deploy sampling still varied: two of three runs passed every
task, while exact JSON and bounded tradeoff tasks each failed once. Prompt instructions
alone do not control provider sampling or native structured-output behavior.

Alpha must improve repeatability without moving provider details into the contract,
weakening validation, retaining raw output, or activating calibrated routing.

## Decision

- Add a versioned provider-neutral generation policy beside the existing output
  contract. Every explicit local contract requests deterministic decoding.
- Exact-JSON contracts request Ollama's native JSON mode. Alpha's provider-neutral
  validator remains responsible for requiring exactly the requested keys because
  version 1 contracts know key names, not value types.
- The Ollama adapter translates deterministic policy to `temperature=0` and `seed=42`,
  and translates structured policy to Ollama's native `format="json"` field.
- The deterministic validator remains authoritative. Native structured output is an
  optimization, never a replacement for contract verification or the quality gateway.
- Initial local calls, the one bounded repair, and local council synthesis receive the
  same policy. Non-contract local calls and all cloud adapters remain unchanged.
- The local benchmark runs three serial samples by default. It passes only when every
  task passes every sample and each task has one canonical response hash across samples.
- Benchmark output remains local-only, metadata-only, advisory, and unable to mutate
  routing scores. Calibrated routing remains off.

```text
Output contract
    -> provider-neutral generation policy
    -> Ollama temperature / seed / JSON mode
    -> deterministic contract validator
    -> one repair at most
    -> repeated-run stability gate
```

The implementation follows Ollama's documented
[structured JSON mode](https://docs.ollama.com/capabilities/structured-outputs) and
[temperature and seed controls](https://docs.ollama.com/modelfile).

## Operations

Plan the three-sample benchmark without model calls:

```bash
python scripts/benchmark_local_output_contract.py
```

Run the local stability gate with its worst-case 24-call cap:

```bash
python scripts/benchmark_local_output_contract.py \
  --live \
  --samples 3 \
  --max-calls 24 \
  --output /path/outside-git/local-output-stability.json
```

## Rollout and Rollback

1. Keep calibrated routing off.
2. Confirm the zero-call `output_contract` eval group requests deterministic and
   structured decoding.
3. Run the three-sample benchmark on the deployed local model and require its stability
   gate to pass.
4. Treat a model, Ollama, quantization, or hardware change as new evidence; rerun the
   gate rather than assuming historical hashes remain valid.

Rollback is code-only: remove generation-policy arguments from chat and restore the
router's prior unconstrained local request. No database, migration, secret, corpus, or
routing-policy rollback is required.

## Consequences

- Exact JSON syntax can be constrained during generation; Alpha still enforces keys.
- Fixed sampling reduces avoidable output variance and repair latency.
- Identical output hashes are runtime-specific evidence, not a cross-hardware guarantee.
- Some valid but textually different answers will fail the strict stability gate. That
  is intentional for Phase 30 evidence and does not alter the user-facing quality gate.
