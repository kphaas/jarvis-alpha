# D3 Dream Orchestrator — Design

**Session:** 2026-04-19
**Status:** LOCKED — ready for D3.1 schema migration
**Supersedes:** 5 open questions in HANDOFF_2026-04-18_01.md

---

## Purpose

Lock the architecture for the D3 Dream Orchestrator before writing code or migrating schema. Each decision validated against big-tech patterns (Temporal docs, production agent frameworks) to minimize technical debt.

---

## Context

- Dream Mode = autonomous overnight agent that plans/reviews/executes tasks while operator sleeps
- D1 (safety infra) and D2 (planner/reviewer services) shipped. D3 wires them together via Temporal.
- Prerequisites complete: Temporal POC passed, planner/reviewer services live, cost caps / invariants / kill switch / model policy all live
- First Dream workflow target: overnight briefing dispatch (linear, low-risk)

---

## Decisions

### Q1 — Session state

**Decision:** Temporal owns real session state. A `status` column in `alpha_dream_sessions` is a denormalized snapshot for UI/audit only.

**Status values (5):** `pending → running → completed | failed | killed`

**Replan tracking:** separate `replan_count INT` column — not status sub-states.

**Rationale:**
- Temporal Event History is the durable truth — workflow code defines transitions
- Temporal's position: "Workflows automatically hold state over long periods of time, so you don't need state machines"
- Custom state machine duplicates Temporal's job, creates drift risk between DB and workflow state
- UI needs a simple string column — this gives exactly that without introducing a second source of truth

**Non-goals:**
- No custom transition validation logic
- No DB triggers on status changes
- Status is write-only from workflow at phase transitions

---

### Q2 — Revision loop

**Decision:** Reviewer feedback fed back to planner on `NEEDS_REVISION`. Max 2 replans (3 total attempts), then `failed` + DLQ entry.

**Retry policies per error class:**

| Error class | Max attempts | Backoff |
|---|---|---|
| LLM rate limit (429) | 5 | Exponential, 1s → 60s |
| LLM timeout | 3 | Exponential, 1s → 30s |
| LLM malformed output | 2 | Immediate |
| Reviewer NEEDS_REVISION | 2 replans | None (bounded loop) |
| Invariant violation | 0 | Non-retryable |
| Cost cap exceeded | 0 | Non-retryable |
| Kill switch fired | 0 | Non-retryable |

**Rationale:**
- Temporal docs: "LLM activity retry policies should be defined per error class, not as a single catch-all"
- Unbounded retry is a documented production failure mode for LLM agents
- Bounded retry with context is the canonical pattern (Replit, Retool, temporal-ai-agent reference impl)

**DLQ entry contents:** session_id, final error class, replan_count, last planner output, last reviewer output, timestamp.

---

### Q3 — Step execution

**Decision:** Dream steps become Temporal activities inside the Dream workflow. Do NOT reuse the existing TaskGraph executor.

**Activity catalog (D3 scope):**
- `plan_session` — calls planner service
- `review_plan` — calls reviewer service
- `check_invariants` — runs R1–R15 checker
- `check_cost_cap` — pessimistic-lock cost reservation
- `dispatch_llm` — cloud LLM call via Gateway
- `notify_approval` — Pushover if approval required
- `write_session_result` — persist final output

**Deployment:**
- New Temporal worker LaunchAgent on Brain: `com.jarvis.alpha.temporal.worker`
- Existing TaskGraph executor (`com.jarvis.alpha.executor`) untouched — continues handling non-Dream graphs
- Activities registered via single omnibus worker (per TEMPORAL_DECISION.md)

**Rationale:**
- Temporal docs: activities are canonical granularity; splitting into separate activities makes failures easier to track, debug, recover from
- Reusing TaskGraph executor would create bidirectional coupling (TaskGraph knows about Dream, Dream knows about TaskGraph) — high debt
- Clean separation lets each subsystem evolve independently

---

### Q4 — Parallel vs sequential

**Decision:** Sequential-by-default. Activities written `async def` so parallelism is a one-line upgrade via `asyncio.gather()` when a real use case lands.

**Pattern:**
```python
# Sequential (D3 default)
for step in steps:
    result = await workflow.execute_activity(step, ...)

# Parallel (when needed — 1-line change)
results = await asyncio.gather(*[
    workflow.execute_activity(step, ...) for step in steps
])
```

**Rationale:**
- First Dream workflow (overnight briefing dispatch) is linear by nature
- Cost cap uses pessimistic locking — parallel cloud steps serialize at the DB anyway
- Temporal makes parallelism trivial (`asyncio.gather` is the textbook fan-out pattern)
- YAGNI: no preemptive parallelism without a proven use case
- Async-native activities mean zero retrofit cost when parallelism is actually needed

**When parallelism lands (D4 or later):**
- Requires cost cap refactor to reservation model (not pessimistic lock)
- Revisit after first parallel use case is identified

---

### Q5 — Temporal workflow contract

**Decision:** One Temporal workflow per Dream session. Steps as activities inside. No child workflows for D3.

**Mapping:**
- `alpha_dream_sessions` row ←→ one Temporal workflow execution
- `workflow_id` = session UUID
- `workflow_type` = `DreamSessionWorkflow`
- Steps = activities within that workflow

**Rationale:**
- Temporal docs: "Every workflow should be limited in size, but we can infinitely scale out the number of workflows"
- At our scale (one session per night), workflow = session is the simplest useful unit
- Event History limit (51,200 events) not a concern — a typical Dream session generates ~50 events
- Child workflows add complexity without benefit at current scale

**When child workflows might be needed:**
- If step count per session exceeds ~1000 (not our case)
- If we add multi-agent fan-out with independent retry semantics (D5+)

---

## Out of Scope for D3

Explicitly deferred:

| Feature | Why deferred | Target |
|---|---|---|
| Saga / compensation pattern | Dream activities are idempotent; no external side effects yet | D5+ if email/Matrix/external actions added |
| Parallel step execution | No proven use case; first workflow is linear | D4 or when first parallel use case lands |
| Child workflows | Scale doesn't warrant it (1 session/night) | D5+ if iteration count explodes |
| Continue-As-New | Event history limit far from reached | Never, unless workflow history > 10K events |
| Multi-agent fan-out | Not a D3 use case | D5+ |

---

## Schema Preview — D3.1

Expected changes to `alpha_dream_sessions` (from `008_dream_mode.sql`):

**Additions:**
- `temporal_workflow_id TEXT UNIQUE NOT NULL` — links DB row to Temporal execution
- `temporal_run_id TEXT` — current run ID
- `replan_count INT NOT NULL DEFAULT 0` — tracks revision loop iterations
- `dlq_entry_id UUID` — FK to DLQ table when failed

**Modifications:**
- Confirm `status` column CHECK constraint allows: `pending, running, completed, failed, killed`

**Activity boundary writes:**
- Only the workflow updates `status`. No other service writes this column.
- Audit columns (`created_at`, `updated_at`, `started_by`) per audit attribution standard.

Also: `alpha_cloud_costs.session_type` CHECK constraint must add `'dream'` (currently `['ask','overnight','forge','other']`).

Full migration spec in D3.1 session.

---

## First Dream Workflow — Overnight Briefing Dispatch

Per TEMPORAL_DECISION.md, the first port is overnight briefing dispatch. Linear, low risk. Planned activity sequence:

1. `plan_session` — plan the briefing content (cloud LLM call)
2. `review_plan` — reviewer validates plan
3. `check_invariants` — R1–R15 check against plan
4. `check_cost_cap` — reserve cost budget
5. `dispatch_llm` — generate briefing text
6. `write_session_result` — persist to DB

No approval step for briefing (read-only output). Approval activity will come with first write-action workflow (D4+).

---

## Implementation Order

| Phase | Deliverable | Est |
|---|---|---|
| D3.1 | Schema migration (extend `008_dream_mode.sql` per preview above) | 1 session |
| D3.2 | Temporal server LaunchAgent on Brain + Postgres persistence (separate `temporal` DB) | 1 session |
| D3.3 | Omnibus worker LaunchAgent on Brain | 0.5 session |
| D3.4 | Activity implementations (7 activities above) | 1–2 sessions |
| D3.5 | `DreamSessionWorkflow` definition | 1 session |
| D3.6 | First workflow port: overnight briefing dispatch end-to-end | 1 session |
| D3.7 | Temporal Web UI exposed via nginx `alpha.conf` (observability) | 0.5 session |

Total: 5–7 sessions to complete D3.

---

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Temporal Postgres migration from SQLite POC | Medium | D3.2 dedicated session; separate `temporal` DB from `jarvis_alpha` |
| Worker LaunchAgent secrets path | Low | Follow existing LaunchAgent pattern (bash + start script + source secrets) |
| Activity determinism (LLM nondeterminism inside workflow) | Medium | All LLM calls MUST be inside activities, never in workflow code |
| Cost cap serializes parallel steps | Low | Acknowledged; sequential-by-default avoids the issue for D3 |
| Event history growth if activities log large payloads | Low | Claim-check pattern if needed (DB reference instead of inline) |

---

## References

**Internal:**
- `docs/TEMPORAL_DECISION.md` — GO verdict, tech choices locked
- `docs/DREAM_MODE_SPEC.md` — Dream Mode overall spec
- `docs/state/STATE_2026-04-18.md` — infrastructure state at D3 entry
- `docs/JARVIS_Alpha_Phase_Status.md` Addendum 2026-04-18 — interim canonical phase status
- `HANDOFF_2026-04-18_01.md` — 5 open questions this doc resolves

**External validation (big-tech patterns, Apr 19 2026):**
- Temporal docs — workflow/activity model, state machines superseded by Event History, retry policies
- Temporal AI cookbook — LLM agent patterns, retry per error class
- `temporalio/samples-python` — canonical `asyncio.gather` fan-out pattern
- Production failure pattern analysis — unbounded retry, child workflow cancellation, event history limits
- Temporal blog — "Every workflow should be limited in size, but we can infinitely scale out the number of workflows"

---

*D3 Dream Orchestrator Design · Locked 2026-04-19 · Next: D3.1 schema migration session*
