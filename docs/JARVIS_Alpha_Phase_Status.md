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

*JARVIS Alpha Phase Status · April 6 2026 · github.com/kphaas/jarvis-alpha*
