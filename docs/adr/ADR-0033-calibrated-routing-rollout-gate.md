# ADR-0033: Gate Outcome-Calibrated Chat Routing

Date: 2026-07-13

Status: Proposed

Related: Phase 23 Outcome-Calibrated Model Scores, Phase 26 Calibrated Routing Rollout Gate

## Context

Alpha computes model reliability overlays from compact chat outcome metadata, but
static capability scores still own live Auto routing. Applying learned scores
directly would let sparse or degraded observations unexpectedly change provider,
cost, privacy, and latency behavior.

## Decision

Calibrated routing is an explicit, default-off policy at the Alpha router boundary.

- `off` is the kill switch and production default. Static registry capabilities
  remain authoritative and no outcome query is added to chat latency.
- `shadow` computes a bounded candidate from the current user's latest 50 compact
  outcome rows, records the comparison, and never changes the selected route.
- `active` may change an Auto route only when both the static baseline and
  calibrated candidate have at least 10 outcomes.
- Each route's score influence is capped at plus or minus 5 points.
- Active exposure uses a deterministic 1-100 bucket derived from the thread ID.
  Only the bucket is emitted; the rollout key is not logged or persisted.
- Explicit model choices and council execution are outside the rollout.
- After at least 5 applied outcomes, active routing automatically holds if its
  acceptance rate falls below 0.60.
- Invalid policy values fail closed to `off`.

The policy emits metadata-only decision fields through SSE, stored outcome rows,
structured logs, and the deterministic evaluation payload. It stores no prompt,
response, memory, or rollout key.

## Configuration

| Variable | Default | Boundary |
|---|---:|---|
| `ALPHA_CHAT_CALIBRATED_ROUTING_MODE` | `off` | `off`, `shadow`, or `active` |
| `ALPHA_CHAT_CALIBRATED_ROUTING_MIN_SAMPLES` | `10` | 3-100 |
| `ALPHA_CHAT_CALIBRATED_ROUTING_MAX_SCORE_DELTA` | `5` | 1-10 |
| `ALPHA_CHAT_CALIBRATED_ROUTING_PERCENT` | `0` | 0-100 |
| `ALPHA_CHAT_CALIBRATED_ROUTING_ROLLBACK_MIN_SAMPLES` | `5` | 1-100 |
| `ALPHA_CHAT_CALIBRATED_ROUTING_ROLLBACK_ACCEPT_RATE` | `0.60` | 0.0-1.0 |

## Rollout

1. Deploy with `mode=off` and confirm static routing plus rollout metadata.
2. Set `mode=shadow`; gather enough approved outcomes for baseline and candidate.
3. Review candidate changes, quality actions, cost, privacy tier, and latency tier.
4. Set `mode=active` with a small nonzero percentage only after explicit operator
   approval.
5. Increase exposure only while acceptance remains above the rollback floor.
6. Return to `mode=off` for immediate rollback; no data migration is required.

## Consequences

- Lower-tier and cloud routes can improve from observed outcomes without hiding a
  provider change inside static registry mutation.
- Shadow mode adds one bounded user-scoped metadata query per chat request.
- Active routing cannot start from configuration alone when evidence, canary
  percentage, or rollout key is missing.
- The first deployment does not activate calibrated routing.
