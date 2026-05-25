# JARVIS Alpha — Phase Status

Private AI Infrastructure — Clean-Break Rebuild  
**April 6, 2026 · github.com/kphaas/jarvis-alpha · main**  
Sessions K through April 6 · Alpha-0, Alpha-1, Alpha-2 COMPLETE · Alpha-3 starting

---

## Current Middleware Stack (live on Brain)

```
CORS → Auth → RLS → Approval → RateLimit → Log → handler
```

Scopes enforced per-route via `@require_scopes` decorator (not middleware layer).  
Undecorated routes default to `require_scopes(["*"])` — deny by default.

---

## Alpha-0: Foundation — COMPLETE

| Deliverable | Status |
|---|---|
| Repo scaffold (21 directories) | ✅ |
| Label taxonomy + milestones (Alpha-0 → Alpha-4) | ✅ |
| Postgres schema v1 (215 lines, 13 tables) | ✅ |
| `node_addresses.py` — 12 `os.getenv` calls | ✅ |
| `get_secret()` with access logging | ✅ |
| 7 brain module stubs (504 lines) | ✅ |
| `jarvisalpha_commit.sh` (two-stage deploy) | ✅ |
| Chat thread model locked (7 personal, 5/project) | ✅ |
| jarvis-forge SQLite schema seeded | ✅ |
| GitHub Issues backfill (KI-1 → KI-13) | ✅ |

---

## Alpha-1: Brain Middleware + UI Shell — COMPLETE

| Deliverable | Status |
|---|---|
| RS256 JWT auth on all routes | ✅ |
| CORS locked to Endpoint hostname | ✅ |
| RLS on `alpha_conversation_memory` | ✅ |
| RLS middleware (`RLSContextMiddleware`) | ✅ |
| Rate limit middleware (100 req/min sliding window) | ✅ |
| PIN gate auth (full-screen overlay) | ✅ |
| `apiFetch.ts` / `apiJson<T>()` — Bearer token injection | ✅ |
| 3-tier memory (working/episodic/semantic, 768d embeddings) | ✅ |
| Central model registry | ✅ |
| Buddy agent as LaunchAgent (60s loop) | ✅ |
| UI: Home, Health (partial), Mesh pages | ✅ |
| Auto-scp UI dist on commit (Step 8) | ✅ |
| nginx `alpha.conf` on Endpoint | ⚠️ Live but NOT in git |

---

## Alpha-2: TaskGraph + Security + Approval — COMPLETE

### TaskGraph + Execution

| Deliverable | Status |
|---|---|
| asyncpg connection pool | ✅ |
| TaskGraph DAG schema (`alpha_task_graphs` + `alpha_task_steps`) | ✅ |
| TaskGraph executor | ✅ |
| Kill switch | ✅ |
| Circuit breaker + watchdog | ✅ |

### Service Identity

| Deliverable | Status |
|---|---|
| Per-node RS256 keypairs (Brain, Gateway, Sandbox) | ✅ |
| `iss`-based multi-key auth middleware | ✅ |
| `VALID_ISS_ACTOR_PAIRS` enforcement | ✅ |
| Service token auto-rotation (LaunchAgents, 3 nodes) | ✅ |
| Scope enforcement (`@require_scopes` decorator) | ✅ |
| `jti` (UUID) on all service tokens | ✅ |
| 7-day service tokens, 6-day rotation cycle | ✅ |

### Child Safety

| Deliverable | Status |
|---|---|
| Child profile PIN auth (bcrypt) | ✅ |
| Child RLS — DB-layer enforcement | ✅ |
| Child scopes: `child.ask` + `child.home.read` only | ✅ |
| RLS wired to chat/ask/tasks/dream | ✅ |
| RLS gap fix (`_auto_name_thread`, `escalate_to_overnight`) | ✅ |

### Approval Gateway

| Deliverable | Status |
|---|---|
| Approval schema (migration 010) | ✅ |
| Route classification registry (142 routes, zero gaps) | ✅ |
| T1–T3 pass-through middleware | ✅ |
| T4/T5 blocking queue + 403 with queue_id | ✅ |
| Dedup handling (partial unique index on `status='pending'`) | ✅ |
| Approval routes: unlock, pending, decide | ✅ |
| PIN re-entry (5-min approval JWT, `purpose="approval"`) | ✅ |
| Mark-and-retry with 10-min TTL | ✅ |
| Rich approval notifications (buddy events) | ✅ |
| Approval UI (risk cards, tier badges, countdown timer) | ✅ |
| Startup route audit + CI test | ✅ |

### Dream Mode (foundation)

| Deliverable | Status |
|---|---|
| Dream Mode schema | ✅ |
| Brain routes (8 endpoints) | ✅ |
| Gateway orchestrator | ✅ |
| Kill switch CLI | ✅ |
| Honeypot traps → Postgres | ✅ |

### Engineering Docs

| Deliverable | Status |
|---|---|
| `docs/PATTERNS.md` — engineering gotchas | ✅ |
| `docs/DB_CONTRACTS.md` — table schemas + INSERT patterns | ✅ |
| `docs/SERVICE_CONTRACTS.md` — inter-service communication | ✅ |
| `docs/SERVICE_IDENTITY_MODEL.md` — identity spec (V2) | ✅ |
| `docs/APPROVAL_GATEWAY_SPEC.md` — approval spec (V2) | ✅ |
| `docs/RLS_ROLLOUT_PLAN.md` — RLS rollout spec (V2) | ✅ |

### Infrastructure

| Deliverable | Status |
|---|---|
| `jarvisalpha_pull.sh` hardened restart (unload → kill → purge → load → health) | ✅ |
| Migration 011: `alpha_buddy_events` columns (source, payload) | ✅ |
| Structured JSON logging with `JarvisFormatter` | ✅ |

---

## Alpha-3: Dream Mode + Voice + Polish — STARTING

| # | Task | Est | Priority | Notes |
|---|---|---|---|---|
| 1 | Approval queue expiry cleanup | 30 min | **P1** | Dedup bug: expired `pending` rows block retries |
| 2 | Middleware stack doc update | 10 min | P2 | Spec says Scopes middleware; live uses decorator |
| 3 | nginx `alpha.conf` → git | 20 min | P2 | Config lost if Endpoint rebuilt |
| 4 | Pushover wiring — Gateway `/v1/notify/pushover` | 1 session | P2 | Mobile push for T4/T5 approvals |
| 5 | Dream Mode — overnight loop + morning briefing | 2–3 sessions | P1 | Core Alpha-3 deliverable |
| 6 | Voice UI port from jarvis-core | 1–2 sessions | P2 | STT/TTS, HomePod AirPlay stub |
| 7 | UI refactor — component extraction, custom hooks, lazy loading | 1 session | P3 | Noted but not blocking |
| 8 | Startup route audit → CI enforcement in GitHub Actions | 30 min | P2 | Currently logs only, no CI gate |
| 9 | UniFi real API wiring (stubs today) | 1 session | P2 | WAN + clients return no data |

---

## Alpha-4: Cut Over — PLANNED

Decommission jarvis-core services. Migrate all traffic to jarvis-alpha.  
Prerequisites: Alpha-3 stable, Dream Mode running, Voice UI ported.

---

## Open Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Service tokens expire April 12 | ⚠️ Medium | Rotation tested. LaunchAgents fire ~April 10. Manual check scheduled. |
| Approval queue expiry rows block dedup | ⚠️ Medium | Alpha-3 #1 — transition expired to `status='expired'` |
| nginx `alpha.conf` not in git | ⚠️ Low | 20 min fix, Alpha-3 #3 |
| Pushover is stub only | Low | Buddy events work; no mobile push yet |
| `notification_sent` flag not updated | Low | Cosmetic — notifications delivered via buddy events |
| UI monolith growing | Low | Component extraction queued for Alpha-3 #7 |

---

## Key References

| Item | Value |
|---|---|
| Alpha Brain URL | https://jarvis-brain.tail40ed36.ts.net:8186 |
| Alpha UI URL | https://jarvis-endpoint.tail40ed36.ts.net:4100 |
| Alpha DB | `jarvis_alpha` on Brain Postgres 16 |
| Commit script | `bash ~/jarvis-alpha/scripts/jarvisalpha_commit.sh "msg"` |
| Pull script | `bash ~/jarvis-alpha/scripts/jarvisalpha_pull.sh` |
| Handoffs dir | `~/jarvis-alpha/docs/handoffs/` |
| Secrets (Brain/Gateway) | `~/jarvis/.secrets` |
| Secrets (Sandbox) | `~/.secrets` |
| Service Identity spec | `docs/SERVICE_IDENTITY_MODEL.md` |
| Approval Gateway spec | `docs/APPROVAL_GATEWAY_SPEC.md` |
| RLS Rollout spec | `docs/RLS_ROLLOUT_PLAN.md` |
| DB contracts | `docs/DB_CONTRACTS.md` |
| Service contracts | `docs/SERVICE_CONTRACTS.md` |
| Patterns | `docs/PATTERNS.md` |

---

# Addendum — 2026-04-18

*Apr 6 body above is historical Alpha-2 completion snapshot. This addendum tracks what's shipped since. Next full regen scheduled as TD-99 after D3 Dream Orchestrator lands.*

## Alpha-3 — Progress as of 2026-04-18

Original Alpha-3 table (above) had 9 items. Status updated:

| # | Task | Status | Evidence |
|---|---|---|---|
| 1 | Approval queue expiry cleanup | ✅ SHIPPED | `3f605ff` — `expire_pending_approvals()` SECDEF (TD-45 closed) |
| 2 | Middleware stack doc update | ✅ SHIPPED | `docs/MIDDLEWARE_STACK.md` canonical; scope enforcement via `@require_scopes` decorator |
| 3 | nginx `alpha.conf` → git | ✅ SHIPPED | `8225a98` — committed at `endpoint/nginx/alpha.conf`; deploy via `scripts/deploy_nginx_endpoint.sh` (AI-3 closed) |
| 4 | Pushover wiring — Gateway | ✅ SHIPPED | live-tested with iPhone buzz in D1.7, commit `2510656` |
| 5 | Dream Mode — overnight loop + morning briefing | ⏳ BLOCKED | on D3 orchestrator (5 open questions — see below) |
| 6 | Voice UI port | ⏳ PENDING | Not started — Alpha-3 backlog |
| 7 | UI refactor | ⏳ PENDING | Not started — Alpha-3 backlog |
| 8 | Startup route audit → CI | ⏳ PARTIAL | Logs only; CI gate pending |
| 9 | UniFi real API wiring | ⏳ PENDING | AI-1 — still stub; P1 blocking for operator visibility |

## Alpha-3 — Additional Deliverables Shipped (Not In Original Plan)

### Dream Mode Infrastructure (D1 + D2)

| Deliverable | Status | Evidence |
|---|---|---|
| Planner service | ✅ | commit `4308046` — `brain/services/planner.py` |
| Reviewer service | ✅ | commit `0666faa` — `brain/services/reviewer.py` |
| Cross-family planner/reviewer CHECK | ✅ | migration `20260417_131000_dream_model_policy.sql` |
| Cost caps (per-step/session/night/week/model) | ✅ | `brain/services/dream_cost_cap_service.py` + migration `20260417_120100` |
| Invariant checker R1-R15 | ✅ | `brain/services/dream_invariant_checker.py` + migration `20260417_120000` |
| Multi-signal kill switch | ✅ | `gateway/dream/kill_switch.py` + `alpha_system_flags` + per-step cost governor |
| Postel's Law JSON parsing | ✅ | `brain/services/planner.py::_strip_markdown_fences()` |

### Cost Telemetry Pipeline

| Deliverable | Status | Evidence |
|---|---|---|
| `alpha_cloud_costs` table + RLS | ✅ | migration `20260416_170000_cloud_costs_rls.sql` (TD-65 closed) |
| Model pricing table | ✅ | migration `20260416_080002_model_pricing_table.sql` |
| Audit attribution columns | ✅ | migration `20260416_080000_audit_attribution_columns.sql` |
| `audit_stream_view` | ✅ | migration `20260416_080001_audit_stream_view.sql` |
| 2.5x cost multiplier (Stripe precedent) | ✅ | calibration pending (TD-81) |

### Security & Identity

| Deliverable | Status | Evidence |
|---|---|---|
| FORCE RLS universal | ✅ | 21 tables live (verified 2026-04-18 Brain) |
| SECURITY DEFINER pattern canonical | ✅ | all profile-bearing writes via SECDEF functions |
| Two-token authentication pattern | ✅ | `docs/SERVICE_IDENTITY_MODEL.md` §7.7 + `jarvis-standards/AUTHENTICATION_TWO_TOKEN_PATTERN.md` (TD-86/TD-87 closed) |
| Capability-named scopes | ✅ | `cloud.call`, `dream.plan`, `dream.review`, `dream.execute`, `dream.kill`, `cost.report` |
| Writer role (`jarvis_alpha_writer`, NOBYPASSRLS) | ✅ | for observability writes |
| Canonical GUC — `jarvis.current_user` + `jarvis.role` | ✅ | `app.*`/`rls.*` aliases migrated away (TD-37 closed) |
| Child profile RLS — DB layer | ✅ | AI-6 closed; migration `20260414_180000_child_rls_policies.sql`; 5 RESTRICTIVE policies |
| Audit attribution on approvals | ✅ | `alpha_approval_audit` table + attribution columns |

### Deploy System (Big-Tech Grade)

| Deliverable | Status | Evidence |
|---|---|---|
| Auto SSH fan-out Brain→Gateway→Endpoint | ✅ | `35d34fc` (v1) + `7926c66` (v2) — TD-88 closed |
| Structured `##EVT##` JSON events | ✅ | `scripts/render_events.py` renderer + sentinels |
| Halt-on-fail sequential fan-out | ✅ | Ansible/k8s/CodeDeploy pattern |
| Ansible-style verbosity (`VERBOSE=1`) | ✅ | TD-88 v2 |
| Per-deploy audit log `/tmp/jarvisalpha_commit_*.log` | ✅ | |
| Handoff-skip classifier (docs/handoffs/) | ✅ | `c5bc3b4` — 3s deploys for handoff commits (TD-96 closed) |
| Smart worker / dumb orchestrator split | ✅ | `9981f87` — pull script self-classifies; nodes skip restart for non-runtime changes (TD-107 closed) |
| Renderer skip clarity | ✅ | `12205b0` — show reason instead of stale text (TD-108 closed) |
| LaunchAgent flat directory | ✅ | `806ed45` — all 16 plists in `launchagents/` (TD-105/TD-15 closed) |
| Observability plists committed | ✅ | `com.jarvis.alpha.fluentbit.plist`, `com.jarvis.alpha.loki.plist` |
| nginx deploy script with atomic rollback | ✅ | `scripts/deploy_nginx_endpoint.sh` (AI-3 closed) |

### Infrastructure (General)

| Deliverable | Status | Evidence |
|---|---|---|
| jarvis-core decommissioned | ✅ | 30 LaunchAgents archived on Brain/Gateway/Endpoint (2026-04-04_01) |
| Trace ID = W3C traceparent (32-hex) | ✅ | `brain/middleware/trace_id.py` |
| Grafana Loki + Fluent Bit observability | ✅ | Brain + Sandbox log shippers live |
| Migration runner — raw SQL + SHA-256 + advisory lock | ✅ | 55 migrations in `schema_migrations` (TD-10 closed) |
| Smoke test library v1 | ✅ | `bd296ad` — 3 primitives (TD-57 closed) |
| Bash 5 pinning + runtime guard | ✅ | `#!/opt/homebrew/bin/bash` + `BASH_VERSINFO` guard |

## D3 Dream Orchestrator — Readiness

**Status: NOT READY TO START CODING.** Infrastructure is solid; design questions are not.

### Locked Tech Choices

| Lock | Source |
|---|---|
| Temporal (Homebrew + Python SDK + LaunchAgent) | `docs/TEMPORAL_DECISION.md` verdict GO |
| Own `temporal` Postgres DB on Brain (separate from `jarvis_alpha`) | `TEMPORAL_DECISION.md:119` |
| Single `default` namespace | ibid. |
| Single omnibus worker | ibid. |
| First port: overnight briefing dispatch (linear, low risk) | ibid. |
| `TaskGraphExecutor` class deleted; LaunchAgent `com.jarvis.alpha.executor` remains | `83e1523` (TD-53) |
| Dream planner/reviewer scopes split from dream.execute | `HANDOFF_2026-04-15_04` |

### Five Open Questions — MUST resolve before D3 code

These are blocking. Pure design work. Estimated one session of focused arch review.

1. **Session state machine** — draft → planned → reviewed → executing → completed | failed | killed?
2. **Revision loop** — if reviewer says NEEDS_REVISION, does planner get review feedback + replan, or is this just retry count?
3. **Step execution** — orchestrator dispatches to step runner service, or inline in orchestrator? Reuse existing TaskGraph executor or build separate Dream runner?
4. **Parallel vs sequential steps** — DAG allows parallel; do we execute in parallel or serialize?
5. **Temporal workflow contract** — one workflow per session or one per step?

Once locked, next work is D3.1 — schema migration audit of `alpha_dream_sessions` + `alpha_dream_steps` (from `008_dream_mode.sql`, Apr 5) against locked answers, plus any new columns.

### D3 Readiness Checklist

- [x] Temporal decision GO
- [x] Temporal POC passed
- [x] Planner service shipped
- [x] Reviewer service shipped
- [x] Cost caps live
- [x] Invariants live
- [x] Kill switch live
- [x] Model policy live
- [ ] **5 open architecture questions resolved**
- [ ] D3.1 schema migration written
- [ ] Temporal server + worker LaunchAgent plists
- [ ] First Dream workflow + activities
- [ ] Activity porting (planner, reviewer, invariant check, cost cap check, LLM dispatch, approval notify)

## Risks — Updated

Superseding the "Open Risks" section above with current state:

| Risk | Severity | Status |
|---|---|---|
| Service tokens expire | ✅ RESOLVED | Self-healing rotation — `StartInterval=86400` + `--min-days-remaining 2.0` guard (TD-4 closed) |
| Approval queue expiry rows block dedup | ✅ RESOLVED | `expire_pending_approvals()` SECDEF (TD-45 closed) |
| nginx `alpha.conf` not in git | ✅ RESOLVED | AI-3 closed — committed + deploy script |
| Pushover is stub only | ✅ RESOLVED | Live-tested D1.7 commit `2510656` |
| UI monolith growing | ⏳ Low | Alpha-3 #7 still queued |
| **D3 blocked on 5 architecture questions** | ⚠️ Medium | NEW — blocks Dream Mode overnight loop |
| **Brain watchdog `-15` SIGTERM persisting** | ⚠️ Medium | NEW — PID 3518 — TD-94 partial |
| **Ken PIN still `PLACEHOLDER_MIGRATE_FROM_ALPHA_PIN`** | ⚠️ Low | NEW — migrate via Settings UI (~30s) |
| **Only Forge has `/ready` endpoint** | ⚠️ Low-Medium | NEW — two-endpoint health standard not universal |

## References — Updated

Additional canonical docs shipped since April 6:

| Item | Value |
|---|---|
| Dream Mode spec | `docs/DREAM_MODE_SPEC.md` |
| Temporal decision | `docs/TEMPORAL_DECISION.md` |
| Middleware stack (detailed) | `docs/MIDDLEWARE_STACK.md` |
| Stage discoveries | `docs/STAGE3_DISCOVERY.md`, `STAGE4_DISCOVERY.md`, `STAGE5_DISCOVERY.md`, `STAGE5C_DESIGN.md`, `STAGE5D_DESIGN.md` |
| Smoke library | `docs/SMOKE_LIB_DESIGN.md`, `SMOKE_LIB_DISCOVERY.md` |
| Step 6.5 preflight | `docs/STEP6_5_PREFLIGHT.md` |
| Step 7 discovery | `docs/STEP7_DISCOVERY.md` |
| TD registers (discovery docs) | `docs/TD32_*`, `TD38_*`, `TD40_*`, `TD44_*`, `TD46_*`, `TD60_*` |
| Child RLS hybrid spec | `docs/specs/CHILD_RLS_HYBRID_C_V2.md` |
| Telemetry V2 spec | `docs/specs/TELEMETRY_V2.md` |
| Sandbox Claude runbook | `docs/SANDBOX_CLAUDE_RUNBOOK.md` |
| UI standards | `docs/ALPHA_UI_STANDARDS.md` |
| LaunchAgent conventions | `launchagents/README.md` |
| jarvis-standards cross-repo | `github.com/kphaas/jarvis-standards` (LOGGING.md, AUTHENTICATION_TWO_TOKEN_PATTERN.md) |
| Session state review (today) | `docs/state/STATE_2026-04-18.md` |

---

*Addendum 2026-04-18 · Next: resolve 5 D3 questions → D3.1 schema migration → Temporal wire-up → first Dream workflow. Full architecture regeneration scoped as TD-99 post-D3 ship.*

---

# Addendum — 2026-05-25

## Alpha-3 Dream Mode — D3.4/D3.5 Shipped

The April 18 blocker list above is superseded for Dream Mode orchestration.

| Deliverable | Status | Evidence |
|---|---|---|
| D3 architecture questions resolved | ✅ | Implemented one Temporal workflow per Dream session with planner/reviewer revision loop |
| D3.1 schema metadata | ✅ | `20260524_223000_dream_session_goal_metadata.sql` |
| D3.4 Temporal planner/reviewer workflow | ✅ | PR #112, deployed to Brain/Gateway/Endpoint |
| Dream Temporal worker LaunchAgent template | ✅ | PR #113, `com.jarvis.alpha.temporal.worker` live on Brain |
| Temporal SDK loopback/run-id fixes | ✅ | PRs #114, #115, #118 |
| Gemini reviewer adapter compatibility | ✅ | PR #116 |
| Reviewer JSON wrapping tolerance | ✅ | PR #117 |
| D3.5 kill signal hardening | ✅ | PR #119 wires `/v1/dream/sessions/{id}/kill` to Temporal `halt` signal |
| D3.5 health/stale-session checks | ✅ | PR #119 adds `/v1/dream/health` + worker heartbeat |
| Canonical Dream smoke script | ✅ | `scripts/smoke_dream_temporal.sh` |
| First read-only execution slice | ✅ | PR #119 adds `/v1/dream/sessions/{id}/execute-readonly` |
| Route classification for D3.5 routes | ✅ | PR #120 |
| Write-capable approval gate | ✅ | `/v1/dream/sessions/{id}/execute-gated` queues autonomous side effects for T4/T5 approval before execution |
| Bounded approved write executor | ✅ | `/v1/dream/sessions/{id}/execute-approved` validates approved Dream rows, runs the `publish_dream_briefing` allowlist handler, records verification, and stores compensation metadata |
| Dream RLSContext first slab | ✅ | Frozen `RLSContext`, `set_rls_context()`, and Dream platform helper path landed for approved execution |
| Dream morning briefing surface | ✅ | Dream cleanup publishes `alpha_briefings` rows; `/briefing` UI and Buddy event path surface them |

## Live Verification

| Check | Result |
|---|---|
| Deploy commit | `7dd4aa2` |
| Brain test gate | `171 passed, 0 failed` |
| Temporal worker | LaunchAgent running, heartbeat fresh |
| Canonical smoke | `bash scripts/smoke_dream_temporal.sh` PASS |
| Smoke session | `alpha_dream_sessions.id = 12` |
| Workflow/run | `dream-session-12`, run ID populated |
| Reviewer verdict | `APPROVED` |
| Persisted plan | 12 steps |
| Read-only executor | 4 allowlisted tool steps completed; non-allowlisted/code steps skipped |
| Dream health | `status = ok`, no stale running sessions |

## Remaining Alpha-3 Dream Scope

| Item | Status | Notes |
|---|---|---|
| Write-capable autonomous execution | 🟢 BOUNDED | Approval gate, exact approval/hash validation, `publish_dream_briefing` handler, post-action verification, and compensation metadata are live; future handlers stay allowlist-only |
| Morning briefing generation/UI | ✅ LIVE | Dream sessions synthesize `dream_mode` briefings into `alpha_briefings`, Buddy events, and the `/briefing` UI |
| Dendrite/Matrix notification path | ⏳ DEFERRED | Spec item remains separate from core Temporal execution |
| Voice UI port | ⏳ PENDING | Still outside Dream D3.4/D3.5 |

---

*JARVIS Alpha Phase Status · April 6 2026 · github.com/kphaas/jarvis-alpha*
