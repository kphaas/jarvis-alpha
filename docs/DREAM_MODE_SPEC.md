# DREAM_MODE_SPEC.md — JARVIS Alpha

Autonomous Overnight Agent — Design Specification V1  
April 2026 · github.com/kphaas/jarvis-alpha

---

## 1. Overview

Dream Mode is JARVIS Alpha's autonomous overnight agent. It executes maintenance tasks, generates reports, and prepares a morning briefing while the operator sleeps.

**Core principle:** Brain owns session truth. Gateway initiates and orchestrates. Failures are recoverable. Morning briefing is always generated — even from partial data.

**Design invariants:**
- Gateway is sole internet egress — Brain never touches public internet
- Every action is classified, constrained, and observable
- Child profiles (Ryleigh age 8, Sloane age 5) are never exposed to unfiltered content
- Maintenance always runs — never skipped regardless of LLM plan
- Cost is capped per session — no surprise bills

---

## 2. Architecture

### 2.1 Components

| Component | Node | Role |
|---|---|---|
| Dream Orchestrator | Gateway | LaunchAgent, cron-triggered, builds plans, submits TaskGraphs |
| Dream Executor | Brain | Existing TaskGraph executor — runs steps, records results |
| Dream Watchdog | Brain | Existing watchdog — detects stuck sessions |
| Briefing Generator | Brain | `/v1/dream/briefing` — summarizes session results |
| Notification Service | Gateway | Posts briefing to Dendrite Matrix rooms |
| Fallback Safe Graph | Gateway | Hardcoded maintenance graph — no LLM required |
| Pre-Flight Probe | Gateway | Step 0: health-check all nodes before planning |
| Abort Handler | Brain | `/v1/dream/abort/{session_id}` — human kill switch |

### 2.2 Session Flow

```
1 AM — Gateway LaunchAgent fires (caffeinate -si wraps process)
  │
  ├── Step 0: Pre-flight health probe all 4 nodes
  │     └── If node unreachable → exclude its tasks from graph, note in briefing
  │
  ├── POST /v1/dream/start → Brain checks for active sessions (409 if running)
  │                         → creates dream_sessions row
  │                         → mints session-scoped JWT via /v1/auth/dream-token
  │                         → returns session_id + session_jwt
  │
  ├── ALWAYS: submit fallback safe graph as maintenance prefix
  │     └── Health checks, cert expiry, log patterns, cost report
  │     └── Runs even if LLM planning fails
  │
  ├── Call Claude via local Gateway adapter → plan additional overnight tasks
  │     └── If 429/timeout → skip LLM tasks, maintenance still runs
  │     └── System prompt includes MAX_DREAM_STEPS=30 constraint
  │
  ├── Classify tasks → read_only | idempotent_write | non_idempotent_write | human_gated
  │
  ├── Build TaskGraph DAG (parallel read_only, serial non-idempotent, skip human_gated)
  │     └── Validate: graph ≤ MAX_DREAM_STEPS
  │     └── Validate: non_idempotent tasks have compensation_payload + verification
  │     └── Multi-node non_idempotent → canary_node runs first
  │
  ├── POST /v1/tasks/submit (session_jwt, schema_version) → Brain validates + executes
  │     └── Executor tracks cost_actual_usd per step
  │     └── If cost_budget_usd exceeded → stop, mark budget_exceeded, partial briefing
  │     └── Per-step timeout enforced (default 300s, max 1800s)
  │     └── Resource locks via Postgres advisory locks
  │
  ├── Poll GET /v1/dream/status/{session_id} every 60s
  │     └── If Gateway crashes → Brain watchdog marks session timed_out after timeout
  │
  ├── All steps complete → POST /v1/dream/complete
  │
  ├── Brain generates briefing from dream_session_events
  │     └── Content tagged classification: 30_INTERNAL (child profiles filtered)
  │
  └── Gateway POSTs briefing to Dendrite Matrix
        ├── #jarvis-briefing (always — success or partial)
        └── #jarvis-alerts (only on WARNING/CRITICAL)
```

### 2.3 Session Authority — Brain Owns Truth

Gateway is the initiator. Brain is the single source of truth.

- `dream_sessions` table in `jarvis_alpha` Postgres
- `dream_session_events` append-only event log — every action recorded
- If Gateway crashes, Brain still has all submitted graphs + partial results
- Morning briefing generated from Brain data, not Gateway memory
- Session-scoped trace_id — all logs for one session share the same ID

---

## 3. Database Schema

### 3.1 dream_sessions

```sql
CREATE TABLE dream_sessions (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    started_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at     TIMESTAMPTZ,
    status           TEXT NOT NULL DEFAULT 'running'
                     CHECK (status IN ('running','completed','partial','failed',
                                       'timed_out','budget_exceeded','aborted')),
    mode             TEXT NOT NULL DEFAULT 'live'
                     CHECK (mode IN ('live','dry_run')),
    trigger          TEXT NOT NULL DEFAULT 'scheduled'
                     CHECK (trigger IN ('scheduled','manual','retry')),
    plan_source      TEXT NOT NULL DEFAULT 'llm'
                     CHECK (plan_source IN ('llm','fallback','manual')),
    task_graph_id    UUID REFERENCES alpha_task_graphs(id),
    briefing_sent    BOOLEAN DEFAULT FALSE,
    error_summary    TEXT,
    schema_version   INTEGER NOT NULL DEFAULT 1,
    cost_budget_usd  NUMERIC(8,4) NOT NULL DEFAULT 1.00,
    cost_actual_usd  NUMERIC(8,4) NOT NULL DEFAULT 0.00,
    nodes_available  TEXT[] NOT NULL DEFAULT '{}',
    nodes_excluded   TEXT[] NOT NULL DEFAULT '{}'
);

CREATE INDEX idx_ds_status ON dream_sessions(status);
CREATE INDEX idx_ds_started ON dream_sessions(started_at DESC);
```

### 3.2 dream_session_events

```sql
CREATE TABLE dream_session_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES dream_sessions(id),
    ts              TIMESTAMPTZ NOT NULL DEFAULT now(),
    event_type      TEXT NOT NULL,
    task_step_id    UUID,
    detail          JSONB NOT NULL DEFAULT '{}',
    severity        TEXT NOT NULL DEFAULT 'info'
                    CHECK (severity IN ('info','warning','critical'))
);

CREATE INDEX idx_dse_session ON dream_session_events(session_id, ts);
CREATE INDEX idx_dse_severity ON dream_session_events(severity) WHERE severity != 'info';
```

### 3.3 alpha_task_steps — New Columns

```sql
ALTER TABLE alpha_task_steps
    ADD COLUMN side_effect_type TEXT NOT NULL DEFAULT 'read_only'
        CHECK (side_effect_type IN ('read_only','idempotent_write',
               'non_idempotent_write','human_gated')),
    ADD COLUMN compensation_payload JSONB,
    ADD COLUMN verification JSONB,
    ADD COLUMN timeout_seconds INTEGER NOT NULL DEFAULT 300,
    ADD COLUMN resource_lock TEXT,
    ADD COLUMN canary_node TEXT,
    ADD COLUMN cost_usd NUMERIC(8,4) NOT NULL DEFAULT 0.00;
```

Constraints enforced at application layer:
- `non_idempotent_write` requires `compensation_payload IS NOT NULL`
- `non_idempotent_write` requires `verification IS NOT NULL`
- `timeout_seconds` max 1800
- Multi-node `non_idempotent_write` requires `canary_node IS NOT NULL`

---

## 4. Task Classification

Every task node in a Dream Mode graph must declare its side effect type.

| Type | Parallel OK? | Auto-execute? | Compensation? | Verification? | Examples |
|---|---|---|---|---|---|
| `read_only` | Yes | Yes | No | No | Health check, log analysis, cert expiry, cost query |
| `idempotent_write` | Yes | Yes | No | No | Write briefing row, update cost cache, write report |
| `non_idempotent_write` | **Serial only** | Yes | **Required** | **Required** | Kill process, delete temp, restart service |
| `human_gated` | N/A | **No — plan only** | N/A | N/A | Code changes, deploys, security patches |

### 4.1 Compensation Tasks

Non-idempotent tasks store a rollback payload:

```json
{
    "side_effect_type": "non_idempotent_write",
    "action": "kill stale process on port 8186",
    "compensation_payload": {
        "command": "launchctl start com.jarvis.alpha.brain",
        "node": "brain",
        "description": "restart Brain service if kill was incorrect"
    },
    "verification": {
        "command": "lsof -i :8186",
        "expected": "empty",
        "node": "brain"
    }
}
```

If the task fails or verification fails:
1. Executor runs `compensation_payload`
2. Marks step `action_unverified` or `rolled_back`
3. Flags in briefing with full context

### 4.2 Progressive Execution (Canary)

For `non_idempotent_write` tasks targeting multiple nodes:
1. Execute on `canary_node` first
2. Verify success
3. If canary passes → fan out to remaining nodes
4. If canary fails → skip remaining, mark step `canary_failed`

### 4.3 Resource Locking

Steps with `resource_lock` set acquire a Postgres advisory lock before execution:

```python
SELECT pg_try_advisory_lock(hashtext('port:8186'))
```

- If lock acquired → execute
- If locked by another step → wait up to `timeout_seconds`, then skip with `resource_contention`
- Lock released on step completion (success or failure)

---

## 5. Fallback Safe Graph

If LLM planning fails (429, timeout, API down), Gateway submits this hardcoded graph. This graph also runs as a **mandatory prefix** on every session — maintenance is never skipped.

| Step | Task | Type | Timeout | Parallel Group |
|---|---|---|---|---|
| 1 | Health check all available nodes | read_only | 30s | A |
| 2 | TLS cert expiry check | read_only | 10s | A |
| 3 | Loki log pattern analysis (24h) | read_only | 120s | A |
| 4 | Postgres connection count + table sizes | read_only | 15s | A |
| 5 | Cost report (last 24h) | idempotent_write | 30s | B (after A) |
| 6 | Generate briefing | idempotent_write | 30s | C (after B) |

Steps 1–4 run in parallel (group A). Steps 5–6 run serial after group A completes.

---

## 6. Execution Constraints

### 6.1 Graph Size Limit

```
MAX_DREAM_STEPS = 30 (configurable via ~/jarvis/.secrets)
```

Brain rejects graphs exceeding this limit at `/v1/tasks/submit`. LLM planner system prompt includes this constraint to prevent over-generation.

### 6.2 Per-Step Timeout

Every `alpha_task_steps` row has `timeout_seconds`:
- Default: 300 (5 min)
- Maximum: 1800 (30 min)
- Executor kills the step process after timeout
- Step marked `timed_out`, graph continues other branches

### 6.3 Cost Budget Enforcement

- `dream_sessions.cost_budget_usd` default: $1.00
- Executor sums `cost_usd` across all completed steps
- Updates `dream_sessions.cost_actual_usd` after each step
- If `cost_actual_usd >= cost_budget_usd` → stop executing remaining steps
- Session marked `budget_exceeded`
- Partial briefing generated with cost breakdown

### 6.4 Session Deduplication

Brain `/v1/dream/start` checks:

```sql
SELECT id FROM dream_sessions WHERE status = 'running';
```

If a running session exists → return 409 Conflict. Orchestrator logs and exits cleanly. Prevents `KeepAlive=true` from spawning duplicate sessions.

---

## 7. Pre-Flight Health Check

Step 0 of every session, before planning:

```
Gateway probes:
  GET https://jarvis-brain.tail40ed36.ts.net:8186/health     (timeout 10s)
  GET https://jarvis-gateway.tail40ed36.ts.net:8283/health    (timeout 10s — self-check)
  GET https://jarvis-endpoint.tail40ed36.ts.net:4100/health   (timeout 10s)
  GET https://100.124.172.14:5001/health                       (timeout 10s — Sandbox)
```

- Available nodes recorded in `dream_sessions.nodes_available`
- Unavailable nodes recorded in `dream_sessions.nodes_excluded`
- Tasks targeting excluded nodes are removed from the graph
- Session proceeds with reduced scope — does not fail
- Briefing notes which nodes were excluded and why

---

## 8. Dry-Run Mode

`dream_sessions.mode = 'dry_run'`

Full session flow with one difference: executor logs "would execute" instead of running commands.

- LLM planning runs normally
- TaskGraph submitted normally
- Executor processes each step but skips actual execution
- Logs structured: `{"action": "dry_run", "step": "...", "would_execute": "..."}`
- Briefing generated showing what would have happened
- Cost tracking: estimates only, no actual API calls

Trigger dry run:
- Manual: `POST /v1/dream/start {"mode": "dry_run"}`
- UI button: "Test Dream Mode"

---

## 9. Human Kill Switch

### 9.1 Abort Endpoint

```
POST /v1/dream/abort/{session_id}
Authorization: Bearer <user_jwt>
```

Brain behavior:
- Running steps: allowed to finish current operation (no mid-command kill)
- Pending steps: marked `cancelled`
- Session status: `aborted`
- Partial briefing generated immediately
- `dream_session_events` records abort with user identity

### 9.2 Abort Channels

| Channel | Method |
|---|---|
| Alpha UI | "Stop Dream Mode" button on Briefing page |
| Matrix | Reply "stop" in #jarvis-briefing → webhook → abort |
| CLI | `curl -sk -X POST .../v1/dream/abort/{id} -H "Authorization: Bearer $(gen_test_token.py)"` |

---

## 10. JWT — Session-Scoped Token

### 10.1 Token Minting

Gateway calls Brain to mint a session-scoped token. Brain keeps sole custody of the JWT private key.

```
POST /v1/auth/dream-token
Authorization: Bearer <gateway_service_token>
Body: {"session_id": "...", "max_duration_hours": 6}
```

Response:
```json
{
    "token": "eyJ...",
    "expires_at": "2026-04-05T07:30:00Z"
}
```

### 10.2 Token Properties

| Property | Value |
|---|---|
| Algorithm | RS256 (same as user JWT) |
| Subject | `dream-mode-agent` |
| Expiry | `session_start + max_duration + 30min` |
| Claims | `session_id`, `role: dream_agent` |
| Allowed actions | `task_submit`, `task_status`, `dream_status`, `dream_complete` |

Brain validates:
- Rejects tokens without `session_id` claim on dream endpoints
- Rejects tokens with `role: dream_agent` on non-dream endpoints
- Logs all dream agent actions with session_id for audit trail

---

## 11. Notification — Dendrite Matrix

### 11.1 Server

| Item | Value |
|---|---|
| Server | Dendrite (lightweight Matrix homeserver) |
| Location | Unraid NAS (192.168.30.10) |
| Why Unraid | If Brain is down, notifications still flow |
| RAM | ~50 MB |
| Storage | SQLite (single-user, low volume) |
| Access | Gateway reaches via Tailscale or VLAN 30 |

### 11.2 Rooms

| Room | Purpose | Who Sees It |
|---|---|---|
| `#jarvis-briefing` | Morning summary | Ken only |
| `#jarvis-alerts` | Critical alerts | Ken only |
| Future: `#jarvis-family` | Family-safe notifications | Ken + Ryleigh + Sloane (filtered) |

### 11.3 Message Formats

**Briefing (INFO):**
```
🌙 Dream Mode — Session Complete
Started: 1:00 AM | Finished: 3:47 AM | Cost: $0.42 / $1.00 budget
Mode: live | Plan: LLM + maintenance prefix

Nodes: 4/4 healthy
Tasks: 12 completed, 0 failed, 2 human-gated (queued)

Highlights:
  • All 4 nodes healthy
  • Certs valid (74 days remaining)
  • 3 recurring ERROR patterns detected — see Errors page
  • Postgres: 42 connections, 2.1 GB total

Human review queued:
  • F-047: Add retry logic to cloud_routes.py — plan ready
  • F-048: Update seed_backlog.py with new items — plan ready

Full details: https://jarvis-endpoint.tail40ed36.ts.net:4100/briefing
Reply "stop" to abort future sessions.
```

**Alert (CRITICAL):**
```
🚨 Dream Mode — Session Failed
Started: 1:00 AM | Failed at: 1:12 AM
Error: Brain unreachable after 3 retries (pre-flight probe failed)
Nodes excluded: brain
Action required: Check Brain node — SSH jarvisbrain@100.64.166.22

Reply "stop" to prevent retry.
```

**Partial (WARNING):**
```
⚠️ Dream Mode — Partial Completion
Started: 1:00 AM | Stopped: 2:34 AM | Cost: $0.89 / $1.00 budget
Reason: Cost budget exceeded

Completed: 8/14 tasks (maintenance + 2 analysis)
Skipped: 6 tasks (LLM-planned, lower priority)

Full details: https://jarvis-endpoint.tail40ed36.ts.net:4100/briefing
```

### 11.4 Two-Way Interaction (Future)

Ken can reply in `#jarvis-briefing`:
- "approve F-047" → webhook → Brain marks task approved
- "stop" → webhook → abort current/future sessions
- "status" → webhook → current session status
- "rerun" → webhook → trigger manual session

---

## 12. Failure Modes

| # | Failure | Detection | Recovery |
|---|---|---|---|
| 1 | Gateway sleeps through cron | No `dream_sessions` row by 2 AM | `caffeinate -si` wraps LaunchAgent; `pmset sleep 0` on Gateway; Brain checks for missing session via Buddy |
| 2 | LLM planning fails (429/timeout) | Catch in orchestrator | Maintenance prefix still runs; LLM tasks skipped; briefing notes "fallback only" |
| 3 | Brain unreachable | Gateway HTTP timeout on pre-flight | Log locally, retry 3x at 5-min intervals, alert to Matrix, session runs without Brain tasks |
| 4 | Task step fails | Executor marks step `failed` | Continue other branches; run compensation if non-idempotent; flag in briefing |
| 5 | Gateway crashes mid-session | Brain watchdog detects stuck graph | Mark session `timed_out`; generate partial briefing from Brain data |
| 6 | JWT expires mid-session | Brain returns 401 | Session token has generous expiry (duration + 30min); orchestrator handles re-auth |
| 7 | Dendrite down | POST fails | Retry 3x; fallback: write briefing to Postgres + Buddy events; UI shows it |
| 8 | Duplicate session attempt | Brain returns 409 | Orchestrator logs and exits cleanly |
| 9 | Cost budget exceeded | Executor tracks cumulative | Stop execution, mark `budget_exceeded`, partial briefing |
| 10 | Gateway dead + Brain can't alert | Brain writes `dream_alert` to Postgres | Dashboard shows alert on next UI visit; Buddy event visible |
| 11 | Post-action verification fails | Verification command returns unexpected | Mark `action_unverified`, run compensation, flag in briefing |
| 12 | Resource contention | Advisory lock held | Wait up to timeout, then skip with `resource_contention` |
| 13 | Graph exceeds MAX_DREAM_STEPS | Brain rejects at submit | Orchestrator truncates graph to limit, notes truncation in briefing |
| 14 | Canary node fails | Canary step returns error | Skip remaining nodes for that task, mark `canary_failed` |

---

## 13. Child Profile Safety

Dream Mode runs as `dream-mode-agent` with `role: dream_agent`.

### 13.1 Content Classification

All Dream Mode output is tagged `classification: 30_INTERNAL`:
- Briefing content in `dream_session_events`
- Reports written to Postgres
- Log analysis summaries

### 13.2 UI Enforcement

- RLS policy filters `30_INTERNAL` content from child profiles (Ryleigh, Sloane)
- If a child opens the dashboard at 7 AM, Dream Mode briefing is not visible
- Family-safe summary can be generated separately for `#jarvis-family` Matrix room (future)

### 13.3 Agent Identity

Dream agent JWT includes:
- `role: dream_agent`
- `content_classification: 30_INTERNAL`
- Brain middleware enforces classification on all write operations

---

## 14. Observability

| Item | Value |
|---|---|
| Gateway logs | `service: dream_orchestrator`, `node: gateway` |
| Brain executor logs | `service: dream_executor`, `node: brain` |
| Trace ID | Session-scoped — all logs for one session share the same trace_id |
| Audit trail | `dream_session_events` — append-only, never deleted |
| Errors page filter | `service: dream_*` shows all Dream Mode logs |
| Loki labels | `{service="dream_orchestrator", node="gateway"}` |
| Cost visibility | `dream_sessions.cost_actual_usd` updated per step |

---

## 15. LaunchAgent Configuration

### 15.1 Gateway Plist

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.jarvis.alpha.dream</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/caffeinate</string>
        <string>-si</string>
        <string>/bin/bash</string>
        <string>/Users/infranet/jarvis-alpha/scripts/start_dream_mode.sh</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>1</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>WorkingDirectory</key>
    <string>/Users/infranet/jarvis-alpha</string>
    <key>StandardOutPath</key>
    <string>/Users/infranet/jarvis-alpha/logs/dream_mode.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/infranet/jarvis-alpha/logs/dream_mode_error.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>JARVIS_NODE</key>
        <string>gateway</string>
        <key>SECRETS_FILE</key>
        <string>/Users/infranet/jarvis/.secrets</string>
    </dict>
</dict>
</plist>
```

### 15.2 Gateway System Sleep Prevention

One-time setup on Gateway:

```bash
sudo pmset sleep 0
sudo pmset disablesleep 1
```

---

## 16. Brain Routes — Dream Mode API

| Route | Method | Purpose |
|---|---|---|
| `/v1/dream/start` | POST | Create session, mint JWT, check dedup |
| `/v1/dream/status/{session_id}` | GET | Session status + step progress |
| `/v1/dream/complete` | POST | Mark session complete, trigger briefing |
| `/v1/dream/abort/{session_id}` | POST | Human kill switch — cancel pending steps |
| `/v1/dream/briefing` | GET | Latest briefing (or by session_id) |
| `/v1/auth/dream-token` | POST | Mint session-scoped JWT |

---

## 17. Gap Register

All identified gaps, their severity, and resolution status.

| # | Gap | Severity | Resolution |
|---|---|---|---|
| 1 | Session deduplication | HIGH | Brain rejects if session running (409) — Section 6.4 |
| 2 | Brain can't alert if Gateway dead | HIGH | Two-layer: Dendrite + Postgres/Buddy fallback — Section 12 |
| 3 | No cost cap | HIGH | `cost_budget_usd` column, executor enforces — Section 6.3 |
| 4 | Maintenance skipped by LLM plan | HIGH | Safe graph is mandatory prefix — Section 5 |
| 5 | Matrix overengineered | RESOLVED | Dendrite on Unraid (~50 MB) — Section 11.1 |
| 6 | caffeinate flag insufficient | MEDIUM | `caffeinate -si` + `pmset sleep 0` — Section 15 |
| 7 | Compensation tasks undefined | MEDIUM | `compensation_payload` on task_steps — Section 4.1 |
| 8 | No dry-run mode | HIGH | `mode: live \| dry_run` on sessions — Section 8 |
| 9 | No human kill switch | HIGH | UI + Matrix + CLI abort — Section 9 |
| 10 | No pre-flight health check | HIGH | Step 0: probe all nodes — Section 7 |
| 11 | No per-step timeout | HIGH | `timeout_seconds` on every step — Section 6.2 |
| 12 | No resource locking | MEDIUM | Postgres advisory locks — Section 4.3 |
| 13 | No progressive execution (canary) | MEDIUM | Canary node for multi-node writes — Section 4.2 |
| 14 | No graph size limit | MEDIUM | MAX_DREAM_STEPS = 30 — Section 6.1 |
| 15 | No post-action verification | HIGH | `verification` field on non-idempotent — Section 4.1 |
| 16 | Child profile enforcement | HIGH | Agent identity + classification tagging — Section 13 |

---

## 18. Build Order

| Step | What | Node | Effort | Depends On |
|---|---|---|---|---|
| 1 | Schema migration: `dream_sessions`, `dream_session_events`, `alpha_task_steps` columns | Brain | 45 min | — |
| 2 | `/v1/dream/start`, `/v1/dream/status`, `/v1/dream/complete`, `/v1/dream/abort` Brain routes | Brain | 2 hr | Step 1 |
| 3 | `/v1/auth/dream-token` session JWT minting | Brain | 45 min | Step 1 |
| 4 | Task classification enforcement in executor + timeout + resource locks | Brain | 1.5 hr | Step 1 |
| 5 | Compensation + verification execution logic in executor | Brain | 1 hr | Step 4 |
| 6 | Fallback safe graph definition | Gateway | 30 min | — |
| 7 | Pre-flight health probe | Gateway | 30 min | — |
| 8 | Dream orchestrator + `caffeinate` LaunchAgent | Gateway | 1.5 hr | Steps 2, 3, 6, 7 |
| 9 | LLM planner (Claude via Gateway adapter) | Gateway | 1.5 hr | Step 8 |
| 10 | Briefing generator + `/v1/dream/briefing` | Brain | 1 hr | Step 2 |
| 11 | Dendrite install + config on Unraid | Unraid | 1 hr | — |
| 12 | Notification service (Dendrite Matrix client) | Gateway | 1.5 hr | Steps 10, 11 |
| 13 | Dry-run mode execution path | Brain | 45 min | Step 4 |
| 14 | Abort handler (UI button + Matrix webhook) | Brain/UI | 1 hr | Steps 9, 12 |
| 15 | Briefing UI page | Endpoint | 1 hr | Step 10 |

**Total: ~15 hours across 3–4 sessions**

---

## 19. Open Questions

1. **Dendrite config** — SQLite or Postgres backend on Unraid?
2. **Max session duration** — 4 hours or 6 hours? (default in `dream-token` expiry)
3. **Dream Mode schedule** — fixed 1 AM, or adaptive based on last Ken activity?
4. **Cost budget default** — $1.00 per session reasonable for start?
5. **Matrix two-way interaction** — build webhook handler in Alpha-3 or defer to Alpha-4?

---

## 19A. Implementation Status — 2026-05-25

This V1 spec predates the Temporal D3 implementation. Current production shape is:

| Area | Status | Notes |
|---|---|---|
| Session truth | ✅ Brain-owned | `alpha_dream_sessions` / `alpha_dream_steps` remain canonical |
| Durable orchestration | ✅ Temporal | One workflow per Dream session, task queue `alpha-planning-v1` |
| Planning | ✅ Live | Claude planner via Gateway adapter |
| Review | ✅ Live | Gemini reviewer via Gateway adapter, cross-family policy enforced |
| Revision loop | ✅ Live | Reviewer `NEEDS_REVISION` feeds planner up to policy max |
| Plan persistence | ✅ Live | Approved plan replaces pending session steps |
| Kill path | ✅ Live | `/v1/dream/sessions/{id}/kill` signals Temporal `halt` and blocks pending/running steps |
| Health | ✅ Live | `/v1/dream/health` checks worker heartbeat, Temporal reachability, stale running sessions |
| Canonical smoke | ✅ Live | `scripts/smoke_dream_temporal.sh` creates, starts, polls, health-checks, and read-only executes |
| Read-only execution | ✅ First slice | `/v1/dream/sessions/{id}/execute-readonly` completes allowlisted `tool` / `canary` inspection steps only |
| Write execution | ⏳ Deferred | Requires approval gates, compensation, verification, and kill-switch checks |
| Briefing/Dendrite UI | ⏳ Deferred | Buddy event exists; dedicated morning briefing UX remains |

The current production safety line is intentional: Dream may plan, review, persist,
and execute only narrowly allowlisted read-only inspection steps. Code, cloud, LLM,
and write-capable tool execution remain skipped by the D3.5 executor.

---

## 20. Future Extensions (Not Building Now)

| Extension | Phase | Description |
|---|---|---|
| Self-healing | Alpha-4+ | Auto-restart failed services based on known error patterns |
| Code optimization | Alpha-4+ | Execute refactoring suggestions from overnight analysis |
| Security patching | Alpha-4+ | Apply dependency updates with human approval via Matrix |
| TTS morning briefing | Alpha-3+ | AirPlay WAV to HomePod — one-line redirect when ready |
| Pushover backup | Alpha-3+ | $5 one-time, native iOS critical alerts as Dendrite backup |
| Family notifications | Alpha-4+ | #jarvis-family room with child-safe filtered content |

---

*JARVIS Alpha — Dream Mode Spec V1 · April 2026 · github.com/kphaas/jarvis-alpha*
