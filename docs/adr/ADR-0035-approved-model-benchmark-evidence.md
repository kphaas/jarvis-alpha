# ADR-0035: Ingest Approved Model Benchmark Evidence

Date: 2026-07-14

Status: Proposed

Related: Phase 25 Real Trace Sampling, Phase 26 Calibrated Routing Rollout Gate,
Phase 27 Per-Model Task Benchmarks, Phase 28 Benchmark Evidence Ingestion

## Context

Phase 27 produces compact task scores for registered models, but those output files
are not durable evidence and must not silently alter routing. Operators need a fair
comparison of task quality, latency, cost, deployment, and privacy without retaining
raw prompts or responses.

## Decision

Alpha stores benchmark evidence only after a detached Ed25519 approval.

- The review artifact contains the exact metadata-only benchmark payload, a canonical
  digest, and a domain-separated approval statement.
- The ingestion CLI requires the reviewed artifact, matching digest, signature, and
  public key. It writes an atomic append-only corpus under the configured runtime path.
- The existing trace-approval public key may be reused when the dedicated benchmark
  key path is not configured. Domain-separated statements prevent cross-purpose replay.
- Ingestion rejects unknown fields, raw-content retention flags, unregistered model
  identities, inconsistent scores, duplicate approvals, digest changes, and invalid
  signatures.
- `/v1/chat/evals` exposes the latest approved scorecard per registered model. The
  response includes task scores, latency, cost tier, deployment, privacy tier, model
  ID, evidence digest, and approval reference.
- Evidence remains advisory and explicitly reports `routing_eligible=false` and
  `routing_scores_mutated=false`. It is not read by the capability registry, model
  calibration, or Phase 26 routing planner.
- If the evidence store is absent, the comparison is `empty`. If verification cannot
  complete, the comparison is `unavailable`; Ask and the deterministic eval harness
  continue operating.

## Operations

Create a live metadata file outside Git:

```bash
python scripts/benchmark_chat_models.py \
  --live --models local --max-calls 4 \
  --output /path/outside-git/local-benchmark.json
```

Prepare the exact review artifact:

```bash
python scripts/ingest_chat_model_benchmarks.py \
  --input /path/outside-git/local-benchmark.json \
  --approval-ref phase28-local-YYYYMMDD \
  --prepare-review-output /path/outside-git/local-benchmark.review.json
```

After independent signature approval, ingest with `--review-artifact`,
`--approved-evidence-sha256`, `--approval-signature`, and `--approval-public-key`.

| Variable | Default | Purpose |
|---|---|---|
| `ALPHA_CHAT_MODEL_BENCHMARK_EVIDENCE_PATH` | `logs/chat_model_benchmark_evidence.v1.json` | Runtime evidence corpus |
| `ALPHA_CHAT_MODEL_BENCHMARK_APPROVAL_PUBLIC_KEY_PATH` | trace approval key fallback | Trusted Ed25519 public key |

## Rollout

1. Deploy with no evidence corpus; the operator comparison reports `empty`.
2. Run and review the local benchmark, sign its digest, and ingest one local batch.
3. Obtain explicit paid-egress approval before any brokered/cloud benchmark calls.
4. Review and sign the cloud batch independently, then compare models in Helm.
5. Keep calibrated routing `off` until a separate operator decision explicitly makes
   approved evidence eligible for a bounded shadow policy.

Rollback is code-only. Removing the eval response field and ingestion CLI leaves the
evidence file inert; no database migration or routing rollback is required.
