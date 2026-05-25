# DREAM_MODE_SPEC.md — JARVIS Alpha

Autonomous Overnight Agent — Production Contract V2
Updated 2026-05-25 · github.com/kphaas/jarvis-alpha

---

## 1. Status

Dream Mode is live as a bounded Temporal workflow on Brain. It can create
sessions, plan with Claude through Gateway, review with Gemini through Gateway,
persist approved plans, publish morning briefings, execute a narrow read-only
slice, queue write-capable steps for human approval, and consume approved rows
through a bounded allowlisted writer.

Dream Mode is not an arbitrary autonomous write executor. The only live
approved write handler is the reversible Dream-owned briefing publish path.

This V2 supersedes the April 2026 V1 design that described a Gateway-owned
orchestrator, session-scoped dream JWT minting, Matrix/Dendrite notification,
and TaskGraph execution as the primary path. Those ideas are historical unless
reintroduced by a future ADR.

---

## 2. Design Guarantees

- Brain owns session truth in Postgres.
- Temporal owns workflow durability and retry boundaries.
- Gateway remains the only cloud egress path.
- Every Dream route requires an authenticated caller with `dream.execute` or an
  admin user JWT; kill also requires `dream.kill`.
- Child profiles never see Dream output.
- Halt flags stop new Dream execution before side effects.
- Read-only execution does not call shell, mutate state, call LLMs, or call the
  network.
- Write-capable steps are queued through the Approval Gateway before bounded
  execution may run them.
- Approved write execution re-checks halt flags, validates the exact approval
  row and parameters hash, runs an allowlisted handler only, records post-action
  verification, and stores compensation metadata.
- All database writes to FORCE-RLS Dream tables run in a transaction with
  `rls.role = platform_admin`.
- Runtime targets must come from config helpers or environment-derived settings,
  not hardcoded IPs, hostnames, or per-user paths.

---

## 3. Current Architecture

| Component | Node | Role |
|---|---|---|
| Brain FastAPI | Brain | Dream HTTP API, auth, RLS binding, health, kill, execution gates |
| Temporal server | Brain | Durable workflow engine on loopback |
| Temporal worker | Brain | Runs `DreamSessionWorkflow` and registered activities |
| Postgres `jarvis_alpha` | Brain | `alpha_dream_sessions`, `alpha_dream_steps`, briefings, Buddy events |
| Gateway adapters | Gateway | Cloud model calls for planner/reviewer only |
| Approval Gateway | Brain/UI | Human gate for T4/T5 write-capable Dream steps |
| Briefing UI | Endpoint | Displays `dream_mode` rows from `alpha_briefings` |
| Buddy events | Brain/UI | Secondary notification surface for Dream completion |

Temporal task queues:

| Queue | Purpose |
|---|---|
| `alpha-dream-workflow-v1` | Dream workflow orchestration |
| `alpha-planning-v1` | Planner/reviewer/persist/cleanup activities |

---

## 4. Session Flow

1. Caller creates a pending session with `POST /v1/dream/sessions`.
2. Caller starts it with `POST /v1/dream/sessions/{id}/start`.
3. Brain checks active halt flags before reserving the workflow.
4. Brain marks the row `running`, records the Temporal workflow id, and starts
   `DreamSessionWorkflow`.
5. The workflow calls planner and reviewer activities.
6. Planner uses the Gateway cloud adapter path; Brain does not call cloud APIs
   directly.
7. Reviewer may request revisions until policy max, then approves or rejects.
8. Approved plans replace pending `alpha_dream_steps`.
9. Cleanup updates final session state, writes an `alpha_briefings` row, and
   records a Buddy event.
10. Optional post-plan execution slices are explicit route calls:
    `execute-readonly` for allowlisted inspection steps, and `execute-gated`
    to queue side-effecting steps for human approval.
11. After approval, `execute-approved` consumes matching Dream approval rows and
    runs only allowlisted write handlers. Today that allowlist contains Dream
    briefing publication.

Canonical smoke:

```bash
bash scripts/smoke_dream_temporal.sh
```

---

## 5. Halt Model

Active halt flags are read from `alpha_system_flags`:

| Flag | Meaning |
|---|---|
| `dream_mode_killed` | Stop Dream execution quickly |
| `dream_emergency` | Emergency halt for critical safety violations |
| `overnight_execution_paused` | Maintenance pause for overnight execution |

The following routes reject with `409 dream_halt_flag_active` when any flag is
active:

| Route | Reason |
|---|---|
| `POST /v1/dream/sessions/{id}/start` | Prevents new Temporal workflow starts |
| `POST /v1/dream/sessions/{id}/execute-readonly` | Prevents even read-only slice execution during pause/kill |
| `POST /v1/dream/sessions/{id}/execute-gated` | Prevents approval queuing during pause/kill |
| `POST /v1/dream/sessions/{id}/execute-approved` | Prevents approved write execution during pause/kill |
| `PATCH /v1/dream/steps/{id}` to `running` or `completed` | Prevents legacy/direct execution transitions |

`GET /v1/dream/health` returns `active_halt_flags` and reports `degraded` while
Dream is intentionally not runnable.

---

## 6. Execution Boundary

### Read-Only Slice

`POST /v1/dream/sessions/{id}/execute-readonly` may complete only persisted
steps that satisfy all of these conditions:

- `agent_type` is `tool` or `canary`
- name/description contains a read-only verb such as `check`, `inspect`,
  `list`, `read`, `summarize`, `validate`, or `verify`
- name/description does not contain write terms such as `create`, `delete`,
  `deploy`, `edit`, `install`, `restart`, `rotate`, `start`, `stop`, `update`,
  or `write`
- dependencies are already `completed` or `skipped`

The read-only executor records acknowledgement metadata only. It does not run a
shell command, call a model, call the network, or mutate anything outside the
Dream step audit fields.

### Write-Capable Gate

`POST /v1/dream/sessions/{id}/execute-gated` classifies non-read-only steps,
queues a T4/T5 approval through `enqueue_dream_step_approval_request`, blocks
the Dream step, and records gate metadata in `alpha_dream_steps.verification`.

### Approved Write Executor

`POST /v1/dream/sessions/{id}/execute-approved` consumes approved Dream rows
only when all of these checks pass:

- accept only explicit allowlisted handlers
- re-check halt flags immediately before execution
- require an approved, non-expired `alpha_approval_queue` row for actor
  `dream_mode`, actor type `agent`, `overnight = true`, matching action classes,
  risk tier, and parameters hash
- record post-action verification
- record compensation metadata and run compensation when verification fails
- consume the approval row only after the attempted write is complete

The current handler allowlist is:

| Handler | Side effect | Verification | Compensation |
|---|---|---|---|
| `publish_dream_briefing` | Upsert `alpha_briefings` for the Dream session | Row exists, source is `dream_mode`, markdown matches generated briefing | Restore prior row snapshot or delete the inserted row |

No shell command, deployment, schema migration, arbitrary SQL writer, network
mutation, or child/family-facing write handler is allowlisted.

---

## 7. Auth And RLS Contract

Dream routes use normal Alpha JWT auth. Admin users bypass scope checks; service
callers need relevant scopes.

| Route class | Auth requirement |
|---|---|
| Session create/list/get/start/health/read-only/gated/approved/briefing | `dream.execute` or admin user |
| Kill | `dream.execute` plus `dream.kill`, or admin user |
| Legacy step updates | `dream.execute` or admin user |

RLS model:

- Human-facing reads use `rls_connection(request)` where request identity should
  flow into RLS.
- Platform-level Dream operations run inside transactions with
  `rls.role = platform_admin`. New platform-owned callers use the frozen
  `RLSContext` and `platform_admin_connection(source="dream", ...)` helper.
- Temporal activities use `brain.dream._db.activity_db()`, which binds
  transaction-scoped `rls.user_id` and `rls.role`.
- Security-definer helpers used by Dream must set `rls.role = platform_admin`
  internally. `enqueue_dream_step_approval_request` does this.

The current pattern preserves the distinction between request-scoped reads and
platform-level Dream execution writes.

---

## 8. Observability

| Surface | Contract |
|---|---|
| `/v1/dream/health` | Worker heartbeat, Temporal reachability, stale sessions, active halt flags |
| Worker heartbeat | JSON file path from `DREAM_TEMPORAL_WORKER_HEARTBEAT`, defaulting under the repo logs directory |
| Temporal ids | `temporal_workflow_id` and `temporal_run_id` on `alpha_dream_sessions` |
| Briefings | `alpha_briefings.source = dream_mode` |
| Buddy event | Dream cleanup publishes a `source = dream` event |
| Approval queue | Side-effecting Dream steps use actor `dream_mode` and action class `dream_autonomous` |
| Tests | Dream workflow, activities, health, read-only execution, gated execution, approved execution, and routes have pytest coverage |

---

## 9. Production Readiness Matrix

| Capability | Status | Notes |
|---|---|---|
| Temporal workflow start | Live | Duplicate workflow starts roll back the DB reservation |
| Planner activity | Live | Cloud call goes through Gateway |
| Reviewer activity | Live | Reviewer JSON tolerance and revision loop live |
| Plan persistence | Live | Approved plans replace persisted steps |
| Kill signal | Live | Signals Temporal and blocks pending/running steps |
| Health endpoint | Live | Includes active halt flags as of 2026-05-25 |
| Read-only execution | Live, narrow | Allowlisted acknowledgement-only slice |
| Write execution | Live, bounded | Approval consumption plus `publish_dream_briefing` allowlist only |
| Morning briefing | Live | `alpha_briefings`, Buddy event, UI |
| Matrix/Dendrite | Deferred | Not part of current production path |
| Voice UI | Deferred | Outside Dream D3 production scope |

---

## 10. Operator Runbook

Check health:

```bash
curl -sk https://jarvis-brain.tail40ed36.ts.net:8186/v1/dream/health \
  -H "Authorization: Bearer ${ALPHA_TOKEN}"
```

Run the canonical smoke from a node that has the Alpha service/user token
loaded:

```bash
bash scripts/smoke_dream_temporal.sh
```

Pause Dream execution:

```sql
UPDATE alpha_system_flags
SET flag_value = true,
    reason = 'operator maintenance window',
    updated_by = 'operator',
    updated_at = now()
WHERE flag_name = 'overnight_execution_paused';
```

Resume Dream execution:

```sql
UPDATE alpha_system_flags
SET flag_value = false,
    reason = 'operator resumed overnight execution',
    updated_by = 'operator',
    updated_at = now()
WHERE flag_name = 'overnight_execution_paused';
```

---

## 11. Remaining Work

| Item | Priority | Notes |
|---|---|---|
| Additional write handlers | P1 before broader autonomy | Add one reversible handler at a time with verifier + compensation |
| Full Dream RLSContext migration | P2 | Existing platform paths still include some explicit `set_config` blocks |
| Scheduled overnight trigger | P2 | Current production shape supports manual/API start and worker execution |
| Notification backup | P2 | Buddy/UI live; Matrix remains deferred |
| Voice UI | P3 | Alpha-3 broader roadmap, not Dream core |

---

*JARVIS Alpha — Dream Mode Spec V2 · Updated 2026-05-25*
