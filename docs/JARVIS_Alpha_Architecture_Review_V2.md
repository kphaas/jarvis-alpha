# JARVIS Alpha — Architecture Review V2

Private AI Infrastructure — Clean-Break Rebuild
Performance · Scalability · Reliability · Security · Autonomous Operations

**April 2026 · github.com/kphaas/jarvis-alpha · main**
Alpha-0, Alpha-1, Alpha-2 complete · Alpha-3 (Dream Mode) in progress · Alpha-5 (containerization) planned

**Supersedes:** Architecture Review V1 (April 2026 — retired by ADR-0002)
**Related:** ADR-0001 (Docker adoption), ADR-0002 (State native, compute containerized), ADR-0003 (Progressive secrets), ADR-0004 (Alpha-5 execution standards)

---

## 1. Design Guarantees — Non-Negotiable Properties

These are enforced at both application and database layers. Every architectural decision must uphold all of them.

- Every action by JARVIS or a JARVIS-created agent is authorized, constrained, and observable.
- No agent can be granted more privilege than the central policy framework allows.
- User identity is cryptographically bound to every API request (RS256 JWT). The user parameter alone is never trusted.
- Child profiles (Ryleigh age 8, Sloane age 5) have real, enforceable guardrails at the database layer, not just application layer.
- Sensitive commands require a second factor regardless of role.
- Failure states are predictable. JARVIS degrades gracefully to the safest possible mode.
- All cloud API calls are gated through the Gateway. Brain never touches the public internet directly.
- Endpoint is pure presentation — no routing logic, no secrets, no direct cloud calls.
- **Hybrid deployment pattern: state native, compute containerized.** State layer (Postgres 16, Ollama, Temporal, SQLite, Tailscale) runs native via macOS LaunchAgent. Compute layer (FastAPI services, nginx, workers) runs in OrbStack containers. See ADR-0002.
- All secrets via `get_secret()`. All IPs/hostnames via `node_addresses.py`. Nothing hardcoded.
- Every service logs structured JSON: `timestamp / level / service / node / message`.
- macOS Keychain is never used in headless LaunchAgent sessions — all app secrets in `~/jarvis/secrets.d/` per-service files (chmod 600). Docker registry credential-helper osxkeychain is a separate and sanctioned pattern (interactive login path; see ADR-0004 §4).

**Historical note:** V1 §1 previously stated "No Docker anywhere — Homebrew native ARM binaries with LaunchAgents only." That rule is retired by ADR-0002. Docker via OrbStack is now the canonical runtime for the compute layer, with the state layer preserved native.

---

## 2. Why jarvis-alpha Exists

jarvis-alpha is a clean-break rebuild of jarvis-core, not an evolution of it. Decision made in Session K.

| Concern | jarvis-core | jarvis-alpha |
|---|---|---|
| Router architecture | Two routers: `router.py` + `adaptive_router.py` — tech debt | Unified orchestrator |
| Overnight planner | Flat task queue — 3/4 tasks deferring nightly | TaskGraph DAG with checkpoint/resume |
| Agent execution | Fragile subprocess pattern | Structured TaskGraph executor |
| Memory | Session-level only | 3-tier: working / episodic / semantic |
| Approval gateway | 258 lines, never mounted | Fully wired (Alpha-2 complete) |
| JWT | Scaffolded, not enforced on all routes | RS256, enforced from Alpha-1 |
| UI | jarvis-core React dashboard (Phase 9) | jarvis-alpha React UI at :4100 |

**Migration strategy:** Option B — paper design first, build in parallel, cut over from jarvis-core when Alpha-5 is stable.

---

## 3. Node Topology

| Node | Machine | Tailscale | User | Alpha Role |
|---|---|---|---|---|
| Brain | Mac Studio M2 Ultra 192GB | `100.64.166.22` / `jarvis-brain.tail40ed36.ts.net` | `jarvisbrain` | FastAPI :8186, Postgres `jarvis_alpha`, Temporal :7233, Buddy, Executor |
| Gateway | Mac Mini M4 16GB / 256GB | `100.98.18.51` / `jarvis-gateway.tail40ed36.ts.net` | `gate` | Cloud adapter (Claude / Perplexity / Gemini) on :8283 |
| Endpoint | Mac Mini M1 24GB | `100.87.223.31` / `jarvis-endpoint.tail40ed36.ts.net` | `jarvisendpoint` | UI :4100 via nginx |
| Sandbox | Mac Mini M4 16GB | `100.69.178.17` / `jarvis-sandbox` (magic DNS) | `jarvissand` | jarvis-forge runner :5001 (HTTPS), CI, feature queue |
| Air | MacBook Air | — | `swetagurnani` | Dev only — never a service node |

**Recent hardware / identity changes:**
- **Gateway (2026-04-20):** M1 (`100.112.63.25`, user `infranet`) retired. Replaced with M4 hardware (user `gate`, new IP). Full preservation tarball executed with `HANDOFF_2026-04-20_Gateway_M1_M4_swap.md` procedure.
- **Sandbox (2026-04-21):** IP drifted to `100.69.178.17`. **Magic DNS `jarvis-sandbox` is stable and preferred** over IP in configs, SSH, and scripts. Repos on Sandbox: jarvis-forge, jarvis-standards, jarvis-alpha, jarvis-financial.

**Network:**
- Unraid NAS: `192.168.30.10` (VLAN 30) — SMB mount, document archive.
- UDM Pro: `192.168.1.1` — AI VLAN 40 (`192.168.40.x`) planned.

---

## 4. Services — Current State

### State layer (native LaunchAgent)

| Service | Node | Port | Protocol | Status |
|---|---|---|---|---|
| Postgres 16 + pgvector (jarvis_alpha DB) | Brain | 5432 | local only | RUNNING |
| Ollama llama3.1:8b | Brain | 127.0.0.1:11434 | local only | RUNNING |
| Ollama qwen2.5-coder:7b | Brain | 127.0.0.1:11434 | local only | RUNNING |
| Temporal server v1.30.4 | Brain | 7233 / 7234 / 7235 / 7243 | loopback only | RUNNING (D3.2 shipped 2026-04-20) |
| Temporal UI v2.48.3 | Brain | 8233 | loopback only | RUNNING |
| Temporal DBs (temporal, temporal_visibility) | Brain | via 5432 | local only | RUNNING |
| Buddy Agent (separate process) | Brain | internal | LaunchAgent | RUNNING |
| TaskGraph executor | Brain | Postgres NOTIFY | LaunchAgent | RUNNING |
| Tailscale daemon | All | kernel | native | RUNNING |

### Compute layer (native today, containerizing in Alpha-5)

| Service | Node | Port | Protocol | Status | Alpha-5 Phase |
|---|---|---|---|---|---|
| FastAPI Alpha Brain | Brain | 8186 | HTTPS Tailscale cert | RUNNING native | Phase 5.5 |
| FastAPI Alpha Gateway | Gateway | 8283 | HTTPS Tailscale cert | RUNNING native | Phase 5.3 |
| nginx Alpha UI proxy | Endpoint | 4100 | HTTPS Tailscale cert | RUNNING native | Phase 5.4 |
| React / Vite Alpha UI | Endpoint | 4100 via nginx | HTTPS | LIVE | Bundled with nginx in Phase 5.4 |

### Other services

| Service | Node | Port | Protocol | Status |
|---|---|---|---|---|
| jarvis-forge dashboard | Sandbox | 5001 | HTTPS Tailscale cert | RUNNING |
| Loki + Grafana (observability) | Brain | TBD | HTTPS | PLANNED (Phase 5.1) |
| `registry:2` (image registry) | Brain | 5000 | HTTPS Tailscale cert | PLANNED (Phase 5.2) |
| Fluentbit forwarders | All | internal | LaunchAgent | PLANNED (Phase 5.1) |
| Overnight Dream Mode (Temporal workflow) | Brain | via Temporal | LaunchAgent | IN PROGRESS (D3.3 next) |
| Voice UI | Endpoint | — | — | NOT YET PORTED |

---

## 5. Commit History and Phase Status

| Session | Alpha Phase | Key Deliverables | Last Commit |
|---|---|---|---|
| K | Decision | Architecture locked — Option B, jarvis-alpha repo, clean break | — |
| L | Alpha-0 | Repo scaffold, label taxonomy, milestones, schema v1, module stubs | `f0a6257` |
| M | Alpha-1 | Brain middleware stack (Auth→RLS→RateLimit), Gateway pure adapter stubs, KI backfill | `8456473` |
| P | Alpha-1 | 3-tier memory, 768d embeddings, central model registry, Buddy agent LaunchAgent | — |
| S | Alpha-1 | PIN auth, CORS, apiFetch, Health/Mesh/Home pages, Sandbox node, UDM Pro bar, auto-scp | `1b5aea8` |
| — | Alpha-2 | asyncpg pool, TaskGraph schema + executor, kill switch, circuit breaker, watchdog, Child RLS, Approval Gateway T1-T5, Service Identity RS256, route classification (142 routes) | `3f605ff` |
| D1 | Alpha-3 | Dream Mode safety infrastructure: invariant checker R1-R15, cost caps, multi-signal kill switch, Postel's Law JSON parsing | multiple |
| D2 | Alpha-3 | Planner service + Reviewer service, real Claude-generated DreamPlans, cross-family CHECK constraints | `4308046`, `0666faa` |
| — (Apr 14) | Alpha-3 | Temporal POC — install, dev server, Python SDK, workflow test, LaunchAgent headless | `63e34f4` |
| — (Apr 19) | Alpha-3 | D3 Orchestrator design locked (5 open architecture questions resolved), D3.1 schema migration | `0ca12f1` |
| D3.2 (Apr 20) | Alpha-3 | Temporal production stack on Brain (server v1.30.4, UI v2.48.3, 2 DBs, LaunchAgents, SDK 1.26.0) | — |
| Gateway Swap (Apr 20) | Ops | M1 → M4 hardware swap; user `infranet` → `gate`; new IP `100.98.18.51`; plist templating pattern proven | `c4208ad` |
| Alpha-5 Planning (Apr 21) | Alpha-5 | ADR-0002, ADR-0003, ADR-0004, ALPHA5_MIGRATION_PLAN.md drafted | this session |

---

## 6. Architecture — Brain

### 6.1 FastAPI Entry — brain/app.py

Middleware stack (LIFO — last added runs first):

```
app.add_middleware(RateLimitMiddleware)    # added 1st → runs 3rd
app.add_middleware(RLSContextMiddleware)   # added 2nd → runs 2nd
app.add_middleware(AuthMiddleware)         # added 3rd → runs 1st
app.add_middleware(CORSMiddleware)         # runs before Auth — allows preflight
```

Execution order per request: **CORS → Auth → RLS → RateLimit → route handler**

CORS: `allow_origins` locked to `https://jarvis-endpoint.tail40ed36.ts.net:4100` only.

Lifespan hook: `recover_stuck_graphs(db_pool)` fires on startup — recovers any graphs left in `running` state from a crash.

### 6.2 Mounted Routes

| Route | File | Key Endpoints |
|---|---|---|
| auth_router | routes/pin_auth.py | POST /v1/auth/pin |
| health_router | routes/health.py | GET /health |
| ask_router | routes/ask.py | POST /v1/ask |
| tasks_router | routes/tasks.py | /v1/tasks/graphs |
| buddy_router | routes/buddy.py | GET /v1/buddy/events |
| memory_router | routes/memory.py | /v1/memory |
| home_router | routes/home.py | GET /v1/home/summary |
| mesh_router | routes/mesh.py | GET /v1/mesh/status |
| unifi_router | routes/unifi.py | /v1/unifi/status, /wan, /clients, /summary |
| costs_router | routes/costs.py | /v1/costs/summary |
| approvals_router | routes/approvals.py | T1-T5 approval queue + decide |
| dream_router | routes/dream.py | /v1/dream/sessions (pre-Temporal; being replaced by Temporal workflow in D3.3) |

### 6.3 JWT Authentication

- Algorithm: RS256
- Private key: `~/jarvis/pki/jwt/jwt_private.pem` (Brain)
- Public key: `~/jarvis-alpha/brain/pki/jwt_public.pem`
- Token lifetime: 30 days
- Skip paths: `/v1/auth/pin`, `/health`, OPTIONS method
- Token storage: localStorage `alpha_token` in UI
- PIN route: POST /v1/auth/pin → validates `ALPHA_PIN` from secrets → issues JWT

### 6.4 Task Dispatch — brain/tasks/dispatch.py

| Agent type | Model | Notes |
|---|---|---|
| call_llm_agent | Ollama llama3.1:8b | 60s timeout, local only |
| call_code_agent | Ollama qwen2.5-coder:7b | System prompt injected |
| call_tool_agent | STUB | WORKER_UPGRADE_PATH comment — migrate to LaunchAgent at >5 concurrent |

Zero cloud calls from dispatch — Alpha fully isolated.

### 6.5 Buddy Agent

- Runs as separate LaunchAgent on Brain (`com.jarvis.alpha.buddy`)
- Async loop every 60s:
 1. `evict_working()` — purge 24hr expired working memory
 2. `promote_to_semantic()` — score episodic, promote high-score to semantic tier
 3. Scan TaskGraph for stuck steps
 4. Write `alpha_buddy_events` rows
- Exposes `/v1/buddy/events` via Brain router (polling, 10s interval)
- UI polls — WebSocket upgrade planned Alpha-3

### 6.6 TaskGraph Executor

- LaunchAgent `com.jarvis.alpha.executor` — runs `python -m brain.tasks.executor`
- Listens on Postgres `graph_submitted` NOTIFY channel
- Start script: `scripts/start_alpha_executor.sh`
- Executor class is NOT deleted in Alpha-2 (despite earlier plan); remains in service

### 6.7 Temporal Stack (D3.2 — shipped 2026-04-20)

- `temporal-server` v1.30.4 + `ui-server` v2.48.3 on Brain
- LaunchAgents: `com.jarvis.alpha.temporal.{server,ui}`
- Ports 7233 / 7234 / 7235 / 7243 / 8233 loopback-only
- Postgres DBs: `temporal` + `temporal_visibility` (owned by `temporal` role, least-privilege)
- Namespace: `default` (72h retention, ID `20422ce3-ccea-4137-a884-cd63b46ca8cd`)
- Python SDK: `temporalio==1.26.0` in `~/jarvis-alpha/.venv`
- Secrets: `TEMPORAL_{DB_PASSWORD,BIND_HOST,BIND_IP,GRPC_PORT,UI_PORT}` in Brain `.secrets`

---

## 7. Architecture — Gateway

Pure adapter pattern — Brain orchestrates all logic.

| Adapter | File | Model / Service |
|---|---|---|
| Claude | adapters/claude_adapter.py | claude-haiku-4-5-20251001 |
| Perplexity | adapters/perplexity_adapter.py | sonar |
| Gemini | adapters/gemini_adapter.py | gemini-2.5-flash |
| Cloud dispatcher | cloud_routes.py | POST /v1/cloud/call |

All adapters use `get_secret()` — no hardcoded keys.

UniFi path: Alpha Brain → Alpha Gateway → UDM Pro (`192.168.1.1`). Secrets `UNIFI_USER`, `UNIFI_PASSWORD`, `UNIFI_BASE_URL` in Gateway `~/jarvis/.secrets`. Wiring still in progress (AI-1).

**Hardware (2026-04-20):** Now running on Mac Mini M4 (16GB / 256GB), user `gate`, IP `100.98.18.51`. Service identity (RS256 keypair) preserved from old M1 Gateway; trusted public key on Brain unchanged.

---

## 8. Architecture — Endpoint / UI

### 8.1 nginx

Config: `endpoint/nginx/alpha.conf` in repo (committed in `8225a98`). Deployed via `scripts/deploy_nginx_endpoint.sh`.
Proxies `:4100` → React UI dist.
Isolated from jarvis-core nginx.

### 8.2 React UI — ui/src

Built on Air, auto-scp to Endpoint on every commit (Step 8 of `jarvisalpha_commit.sh`).

| Page | Status | API endpoints used |
|---|---|---|
| Home | LIVE | /health, /v1/tasks/graphs?limit=1, /v1/home/summary |
| Health | LIVE | /health, /v1/mesh/status, LaunchAgent stanza |
| Mesh | LIVE | /v1/mesh/status (topology with UDM Pro bar) |
| Approvals | LIVE | /v1/approvals/queue, /v1/approvals/decide |
| Errors | PLANNED | — |
| Cost Center | PLANNED | /v1/costs/summary |
| Buddy Events | PLANNED (polling built) | /v1/buddy/events |

### 8.3 Key UI Files

| File | Purpose |
|---|---|
| ui/src/lib/apiFetch.ts | `apiFetch()` and `apiJson<T>()` — all API calls go through this, injects Bearer token |
| ui/src/components/PinGate.tsx | Full-screen PIN overlay, blocks UI until authenticated |
| ui/src/App.tsx | PinGate wraps entire app |
| ui/src/pages/Health.tsx | Node cards, dynamic from API, Lucide icons |
| ui/src/pages/Mesh.tsx | Topology SVG: Brain center, Gateway/Endpoint top, iPhone left, Unraid/Sandbox bottom |
| ui/src/pages/Home.tsx | System status + last overnight — fails independently per section |
| ui/src/pages/Approvals.tsx | T1-T5 queue + decide UI |

---

## 9. Database — jarvis_alpha

### 9.1 Postgres — Brain

DB name: `jarvis_alpha`
DB user: `jarvisbrain`
Full psql path: `/opt/homebrew/Cellar/postgresql@16/16.13/bin/psql`
App role: `jarvis_alpha_app` — never superuser

| Table | Notes |
|---|---|
| alpha_conversation_memory | HNSW vector(768), RLS `alpha_memory_isolation`, 3-tier memory |
| alpha_workspaces | workspace isolation |
| alpha_node_registry | All nodes including Sandbox |
| alpha_buddy_events | Buddy event feed — polled by UI |
| alpha_task_graphs | TaskGraph DAG (Alpha-2 complete) |
| alpha_task_steps | Per-step state (Alpha-2 complete) |
| alpha_projects | project_type: forge \| personal \| problem |
| chat_threads | Max 7 personal, max 5 per project |
| chat_messages | CASCADE delete on thread |
| thread_memory_extracts | What was kept before thread deletion |
| alpha_dream_sessions | D1+D2+D3.1 — includes `temporal_workflow_id`, `temporal_run_id`, `replan_count` |
| alpha_dream_steps | Per-step Dream Mode state |
| alpha_cloud_costs | Cost telemetry (with `session_type='dream'` from Apr 16) |
| alpha_system_flags | Kill switch, safety flags |
| approval_queue | T1-T5 approval system (Alpha-2) |

### 9.2 Memory Tiers

| Tier | Table column | Lifetime | Notes |
|---|---|---|---|
| Working | memory_type='working' | 24 hours | Buddy evicts expired |
| Episodic | memory_type='episodic' | 30 days | Buddy scores + promotes |
| Semantic | memory_type='semantic' | Permanent | Promoted from episodic |

Embeddings: 768-dimensional (upgraded from 384 in jarvis-core).
Retrieval: two-phase RAG — HNSW ANN first, then cosine rerank.
Memory sources tagged: `live | thread_extract | overnight | ingest`.

### 9.3 SQLite — Sandbox

Used by jarvis-forge only. Path: `~/jarvis-forge/memory/feature_queue.db`.
Tables: `features`, `project_registry`, `project_costs`, `project_memory`, `pipeline_runs`.

---

## 10. Secrets and Config

### 10.1 Current state (pre-Alpha-5 Phase 5.0)

| Item | Location |
|---|---|
| Secrets — Brain | `~/jarvis/.secrets` (chmod 600) |
| Secrets — Gateway | `/Users/gate/jarvis/.secrets` (chmod 600) |
| Secrets — Endpoint | `~/jarvis/.secrets` (chmod 600) |
| Secrets — Sandbox | `~/.secrets` (home dir, NOT `~/jarvis/.secrets`) |
| Node addresses | `brain/config/node_addresses.py` — all via `os.getenv` |
| Secret loader | `brain/config/secrets.py` → `get_secret()` with access logging |
| JWT private key | `~/jarvis/pki/jwt/jwt_private.pem` (Brain) |
| JWT public key | `~/jarvis-alpha/brain/pki/jwt_public.pem` |
| Alpha PIN | `ALPHA_PIN` in Brain `.secrets` |
| UniFi creds | `UNIFI_USER`, `UNIFI_PASSWORD`, `UNIFI_BASE_URL` in Gateway `.secrets` |

### 10.2 Target state (post Alpha-5 Phase 5.0)

Per ADR-0003, `~/jarvis/.secrets` monolithic file will be split into `~/jarvis/secrets.d/<service>.env` per-service files with a canonical `MANIFEST.md` that preservation scripts consume. See ADR-0003 for the progressive path.

---

## 11. Deploy and Commit Workflow

### jarvis-alpha Commit Script (two-stage)

`bash ~/jarvis-alpha/scripts/jarvisalpha_commit.sh "msg"`

1. Ruff lint (Air)
2. Build React UI (`npm run build`)
3. Git commit + push (Air)
4. Auto-pull Sandbox (respects `JARVIS_SKIP_SANDBOX=1` flag)
5. Intel refresh fires (project_id=65)
6. SCP `ui/dist/` → Endpoint (auto)
7. Brain / Gateway / Endpoint — **manual pull only** via `jarvisalpha_pull.sh`
8. Manual restart required after pull on Brain / Gateway / Endpoint

### jarvisalpha_pull.sh

Run on each node after commit to pull latest:

```bash
# On Brain
bash ~/jarvis-alpha/scripts/jarvisalpha_pull.sh
```

### Node Labels (prefix above command blocks — never inside)

```
▶ BRAIN —
▶ GATEWAY —
▶ ENDPOINT —
▶ SANDBOX —
▶ AIR —
```

### Plist templating (proven 2026-04-20 on Gateway)

- Per-node plist templates use `{{HOME}}` placeholder
- `scripts/install_launchagents.py --node <n>` renders and installs
- `*.plist` gitignored, `*.template.plist` tracked
- Pattern will migrate to Brain / Endpoint / Sandbox in Alpha-5 Phase 5.0

---

## 12. Security Assessment

| Check | Status | Notes |
|---|---|---|
| RS256 JWT on all routes | PASS | Auth enforced from Alpha-1; SKIP_PATHS: /v1/auth/pin, /health, OPTIONS |
| CORS locked to Endpoint hostname | PASS | allow_origins = https://jarvis-endpoint.tail40ed36.ts.net:4100 |
| RLS on alpha_conversation_memory | PASS | alpha_memory_isolation policy active |
| RLS on chat / ask / tasks / dream | PASS | Wired in Alpha-2 |
| Child profile RLS (Ryleigh / Sloane) | PASS | DB-layer enforcement shipped Alpha-2 |
| Route classification (142 routes, zero gaps) | PASS | Startup audit — Alpha-2 |
| All secrets via get_secret() | PASS | No hardcoded keys in any Alpha source file |
| No hardcoded IPs | PASS | All via node_addresses.py os.getenv |
| nginx alpha config committed | PASS | Committed `8225a98`; deploy via `scripts/deploy_nginx_endpoint.sh` |
| Approval Gateway T1-T5 | PASS | Shipped in Alpha-2 |
| Service Identity RS256 (per-node) | PASS | Shipped in Alpha-2 |
| Per-service secrets splitting | PLANNED | Alpha-5 Phase 5.0 per ADR-0003 |
| Secrets rotation schedule | PARTIAL | Internal service tokens: LaunchAgent stubs exist; automation in Alpha-5 Phase 5.7; cloud API keys manual until Alpha-6 |
| mTLS Brain ↔ Gateway | OPEN | Tailscale mesh provides network-layer encryption today |
| External vault (Infisical / Bitwarden) | PLANNED | Alpha-6 (Phase 5c per ADR-0003) |

---

## 13. Known Issues

| # | Issue | Node | Priority |
|---|---|---|---|
| AI-1 | UniFi WAN + clients are stubs — wire real UDM Pro API | Gateway | P1 |
| AI-2 | Mesh topology visual — Sandbox / iPhone overlap (cosmetic) | Endpoint | P2 |
| AI-4 | dispatch.py call_tool_agent is stub (WORKER_UPGRADE_PATH) | Brain | P1 |
| AI-5 | Agent hierarchy contract not formally documented | All | P2 |
| AI-7 | WebSocket for Buddy events — polling only (10s) | Brain / UI | P2 |
| AI-8 | /v1/home/summary costs_today_usd sometimes null | Brain | P2 |
| AI-9 | Health page LaunchAgent section — partial | UI | P2 |
| AI-10 | Home Service Map — some nodes show "pending" | UI | P2 |
| AI-11 | Executor runs in-process — migrate to LaunchAgent at >5 concurrent graphs | Brain | P3 |
| AI-12 | Worker node architecture — Phase 10+ | All | P3 |
| AI-14 | Sandbox health endpoint — forge dashboard on :5001 not always running | Sandbox | P2 |
| TD-94 | Watchdog LaunchAgent exit -15 / stale executor on Brain | Brain | P1 |
| — | Bootstrap backfill: 6 of 10 expected audit triggers in prod | Brain | P1 |
| — | Gateway Python upgrade (deferred to local session — Tailscale TLS hang) | Gateway | P2 |

**Closed since V1:** AI-3 (nginx alpha.conf committed to git, `8225a98`).

---

## 14. Next Session Priorities

| # | Task | Why | Effort |
|---|---|---|---|
| 1 | D3.3 Dream Mode workflow + activity implementation | First live Temporal workflow | 1-2 sessions |
| 2 | D3.4 Temporal worker LaunchAgent + first live workflow run | End of D3 | 1 session |
| 3 | TD-94 watchdog `-15` SIGTERM investigation | P1 open | 0.5 session |
| 4 | Audit trigger backfill (4 of 10 missing in prod) | Data integrity | 0.5 session |
| 5 | Wire real UDM Pro API in gateway/routes/unifi.py (AI-1) | Stubs ship no data | 1 session |
| 6 | Alpha-5 Phase 5.0 kickoff | Per ALPHA5_MIGRATION_PLAN.md | 2-3 sessions |
| 7 | jarvis-financial kickoff | Apr 21 commitment | 1 session |

---

## 15. Phase Roadmap

| Phase | Title | Key Deliverables | Status |
|---|---|---|---|
| Alpha-0 | Foundation | Repo scaffold, schema, config, stubs, GitHub infra | COMPLETE |
| Alpha-1 | Brain Middleware + UI Shell | JWT, CORS, RLS middleware, Buddy agent, PIN gate, Health/Mesh/Home pages, apiFetch, auto-scp | COMPLETE |
| Alpha-2 | TaskGraph + DB Wiring | asyncpg pool, TaskGraph DAG + executor, kill switch, circuit breaker, watchdog, Child RLS, Approval Gateway T1-T5, Service Identity RS256, route classification (142 routes, zero gaps), PATTERNS.md + DB_CONTRACTS.md + SERVICE_CONTRACTS.md | COMPLETE |
| Alpha-3 | Dream Mode + Voice | D1 safety (invariants + cost caps + kill switch), D2 planner + reviewer, Temporal POC + D3 design + D3.1 schema + D3.2 production stack; **D3.3 workflow + activity impl = NEXT**; D3.4 worker LaunchAgent + first live run; voice UI port | IN PROGRESS |
| Alpha-4 | Cut Over | jarvis-core → jarvis-alpha migration, decommission jarvis-core services | PLANNED (after Alpha-3) |
| **Alpha-5** | **Containerization** | **OrbStack runtime + state/compute split + progressive secrets + per-node Compose + private registry + cert renewal + rotation automation. See ALPHA5_MIGRATION_PLAN.md for 9-phase sequence. Locks: ADR-0002, ADR-0003, ADR-0004.** | **PLANNED** |
| Alpha-6 | Vault + observability deepening | Infisical / Bitwarden deployment (Phase 5c per ADR-0003), Harbor upgrade if scanning / SBOM needed, tracing via OpenTelemetry | PLANNED |

---

## 16. Quick Reference

| Item | Value |
|---|---|
| Alpha Brain URL | https://jarvis-brain.tail40ed36.ts.net:8186 |
| Alpha Gateway URL | https://jarvis-gateway.tail40ed36.ts.net:8283 |
| Alpha UI URL | https://jarvis-endpoint.tail40ed36.ts.net:4100 |
| Alpha DB | `jarvis_alpha` on Brain Postgres 16 |
| Temporal gRPC | 127.0.0.1:7233 (Brain loopback) |
| Temporal UI | 127.0.0.1:8233 (Brain loopback) |
| Brain venv | `~/jarvis-alpha/.venv` (python3.12) |
| Commit script | `bash ~/jarvis-alpha/scripts/jarvisalpha_commit.sh "msg"` |
| Pull script | `bash ~/jarvis-alpha/scripts/jarvisalpha_pull.sh` |
| Gen test token | `python3 ~/jarvis-alpha/scripts/gen_test_token.py` |
| JWT private key | `~/jarvis/pki/jwt/jwt_private.pem` |
| Alpha public key | `~/jarvis-alpha/brain/pki/jwt_public.pem` |
| Secrets (Brain) | `~/jarvis/.secrets` (→ `secrets.d/` in Alpha-5) |
| Secrets (Gateway) | `/Users/gate/jarvis/.secrets` (→ `secrets.d/` in Alpha-5) |
| Secrets (Endpoint) | `~/jarvis/.secrets` (→ `secrets.d/` in Alpha-5) |
| Secrets (Sandbox) | `~/.secrets` (→ `secrets.d/` in Alpha-5) |
| nginx config | `endpoint/nginx/alpha.conf` (in repo) |
| Deploy nginx | `bash scripts/deploy_nginx_endpoint.sh` |
| apiFetch utility | `~/jarvis-alpha/ui/src/lib/apiFetch.ts` |
| PIN auth route | `~/jarvis-alpha/brain/routes/pin_auth.py` |
| JWT middleware | `~/jarvis-alpha/brain/middleware/jwt_auth.py` |
| Dispatch handlers | `~/jarvis-alpha/brain/tasks/dispatch.py` |
| PinGate component | `~/jarvis-alpha/ui/src/components/PinGate.tsx` |
| UniFi Brain proxy | `~/jarvis-alpha/brain/routes/unifi.py` |
| UniFi Gateway route | `~/jarvis-alpha/gateway/routes/unifi.py` |
| Approvals route | `~/jarvis-alpha/brain/routes/approvals.py` |
| Dream routes | `~/jarvis-alpha/brain/routes/dream.py` |
| Planner service | `~/jarvis-alpha/brain/services/planner.py` |
| Reviewer service | `~/jarvis-alpha/brain/services/reviewer.py` |
| Invariant checker | `~/jarvis-alpha/brain/services/dream_invariant_checker.py` |
| Cost cap service | `~/jarvis-alpha/brain/services/dream_cost_cap_service.py` |
| Handoffs dir | `~/jarvis-alpha/docs/handoffs/` |
| Alpha-5 plan | `~/jarvis-alpha/docs/ALPHA5_MIGRATION_PLAN.md` |
| ADRs | `~/jarvis-standards/docs/adr/ADR-{0001..0004}-*.md` |
| Engineering docs | `~/jarvis-alpha/docs/PATTERNS.md`, `DB_CONTRACTS.md`, `SERVICE_CONTRACTS.md`, `MIDDLEWARE_STACK.md`, `D3_ORCHESTRATOR_DESIGN.md` |

---

*JARVIS Alpha Architecture Review V2 · April 2026 · github.com/kphaas/jarvis-alpha · supersedes V1*
