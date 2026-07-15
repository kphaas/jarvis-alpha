# ADR-0043: Adversarial Assisted-Probe Expansion

Date: 2026-07-15

Status: Proposed

Related: Phase 27 Per-Model Task Benchmarks, Phase 30 Deterministic Local
Decoding, Phase 35 Feasible Contract-Failure Corpus Expansion, Phase 37
Historical Evidence Activation Audit, Phase 38 Adversarial Assisted-Probe
Expansion

## Context

Phase 37 found no eligible historical Alpha outcomes because AT-0 had not received
enough real operator use. No raw prompt, response, memory, or conversation content was
accessed. The separate Brain-only baseline benchmark passed 20 of 20 attempts across
four tasks and five samples with zero repairs, but those controlled calls are assisted
evidence, not historical production evidence.

The four baseline tasks prove known contracts remain stable. They are too small to
probe typed JSON values, nulls, distractor citations, negative authorization gates,
dual constraints, and ordered recovery behavior. Replacing them would destroy the
stable comparison point; adding them to every default run would silently double the
local call budget.

## Decision

- Keep the existing four-task `baseline` profile unchanged.
- Add a separately selected, versioned `adversarial` profile with eight reviewed and
  feasible tasks across fast, grounded, analysis, and deep classes.
- Reuse the existing output-contract compiler, deterministic generation policy,
  bounded repair, objective scorer, stability gate, and metadata-only report.
- Require explicit `--profile adversarial` selection. Three samples plan 24 initial
  local calls and at most 48 calls with one repair per attempt.
- Keep the benchmark local-only, advisory-only, and incapable of mutating routing
  scores. Do not retain raw prompts or responses in its result.
- Treat any observed failures as `assisted_probe` evidence. Corpus activation remains
  a separate redaction, review, digest approval, detached-signature, and replay step.

```text
Reviewed adversarial profile
    -> zero-call plan
    -> explicit local-only run on Brain
    -> deterministic contract evaluation
    -> at most one bounded repair
    -> metadata-only stability result
    -> separate signed assisted-probe workflow only for reproducible failures
```

## Four-Lens Rationale

- **Big Tech:** a versioned profile preserves a stable control group while allowing
  harder task expansion through the existing benchmark interface.
- **CIO:** the change reuses current adapters and adds no dependency, service, cloud
  route, database, or Helm surface.
- **Big Finance:** assisted probes remain distinct from historical evidence, call
  volume is bounded before execution, and corpus activation remains operator signed.
- **Designer:** the operator chooses one named profile and receives compact counts,
  stability, repair, privacy, and routing-mutation fields.

## Boundaries

- No historical batch, signed corpus case, calibrated route, production capture path,
  or cloud comparison is activated by this change.
- The benchmark result stores response hashes and objective metadata, not prompt or
  response text. A raw failure review requires a separate approved workflow outside
  Git.
- Task checks are intentionally structural and lexical. They do not claim semantic
  equivalence or general frontier-model capability.
- Live proof must run on Brain, where the configured local Ollama endpoint exists. An
  Air run without that endpoint is invalid model evidence.

## Operations

Plan without model calls:

```bash
python scripts/benchmark_local_output_contract.py \
  --profile adversarial \
  --samples 3
```

Run the bounded local campaign on Brain and write metadata outside Git:

```bash
python scripts/benchmark_local_output_contract.py \
  --profile adversarial \
  --live \
  --samples 3 \
  --max-calls 48 \
  --output /path/outside-git/adversarial-local-output.json
```

## Verification

1. All eight reviewed reference responses score 100 and pass their compiled output
   contracts without repair.
2. The default command remains the unchanged four-task, zero-call baseline plan.
3. The adversarial plan reports 24 initial and 48 maximum local calls for three
   samples, with no prompt or response content.
4. A live command capped below 48 exits before importing or calling the local router.
5. The report remains advisory, local-only, metadata-only, and routing-neutral.

## Rollback

Remove the adversarial task tuple, profile selector, additive profile metadata, CLI
option, and tests. The baseline task definitions and runtime chat path remain
unchanged, so rollback requires no migration, secret rotation, corpus rewrite, or
routing change.

## Consequences

- AT-0 can intentionally generate harder local-model evidence without waiting for
  natural usage or weakening provenance.
- The default benchmark remains comparable to prior evidence.
- A successful profile produces positive assisted evidence only. A reproducible
  post-repair failure may justify a separately approved signed corpus case.
