# Alpha-5 Migration Plan

**Status:** Approved — Ready for Execution
**Date:** 2026-04-21
**Target:** Containerize compute layer of JARVIS Alpha while preserving native state layer
**Expected duration:** 10–13 sessions across ~2–3 months
**ADRs:** ADR-0002, ADR-0003, ADR-0004 (all drafted 2026-04-20 / 2026-04-21)

---

## Table of Contents

1. [Overview](#overview)
2. [Locked Decisions](#locked-decisions)
3. [Migration Principles](#migration-principles)
4. [Phase Sequence](#phase-sequence)
5. [Phase Details](#phase-details)
6. [Service Placement Grid](#service-placement-grid)
7. [Forge Backlog](#forge-backlog)
8. [Validation Criteria](#validation-criteria)
9. [Rollback Procedures](#rollback-procedures)
10. [Out of Scope](#out-of-scope)
11. [Risks and Mitigations](#risks-and-mitigations)
12. [References](#references)

---

## Overview

Alpha-5 migrates the JARVIS compute layer (FastAPI services, nginx, background workers) to OrbStack containers via Docker Compose, while preserving the state layer (Postgres 16, Ollama, Temporal, Tailscale, SQLite) as native LaunchAgent-managed services on the host.

This is **NOT "containerize everything."** The rule is explicit in ADR-0002: **state native, compute containerized.**

### What Alpha-5 accomplishes

- Retires Architecture Review V1 §1 line 23 ("No Docker anywhere"); Architecture Review V2 is the canonical amended review
- Establishes image immutability and rollback for stateless services
- Consolidates `get_secret()` and per-service secrets hygiene
- Unifies observability across native + container surfaces
- Closes F-023 (partial — internal service tokens), F-034 (full — `get_secret()` consolidation)
- Creates a clean path to Alpha-6 vault adoption with zero application code change

### What Alpha-5 explicitly does NOT do

- Kubernetes introduction (not needed at 3-node scale)
- Postgres containerization (state stays native per ADR-0002)
- Ollama containerization (Metal GPU access lost in Docker on macOS)
- External vault deployment (deferred to Alpha-6)
- Mobile iOS app (still deferred — Alpha stability first)

---

## Locked Decisions

Seven foundational decisions are locked and require ADR amendment to revisit:

| # | Decision | Choice | Authority |
|---|---|---|---|
| 1 | Container runtime | OrbStack (macOS-native, Apple Silicon-optimized) | Session 2026-04-21 |
| 2 | Deployment pattern | State native, compute containerized | ADR-0002 |
| 3 | Secrets pattern | Progressive: files → Compose secrets → vault | ADR-0003 |
| 4 | Image registry | `registry:2` on Brain + TLS + htpasswd | ADR-0004 §1 |
| 5 | Compose layout | Per-node files + `deploy/.env` centralized image tags | ADR-0004 §2 |
| 6 | Cert renewal | Staggered LaunchAgent + `tailscale cert --min-validity=120h` + restart | ADR-0004 §3 |
| 7 | Registry pull auth | OrbStack default osxkeychain credential helper | ADR-0004 §4 |

Every decision was independently validated against 2026 industry practice via Perplexity cross-check.

---

## Migration Principles

1. **One node at a time**, one service at a time within each node
2. **Foundation before services** — secrets + observability + registry land BEFORE any service migration
3. **Blue/green cutover** — native LaunchAgent runs until containerized equivalent proves 24h stability
4. **Reversible per phase** — no phase is one-way until Phase 5.7 retirement
5. **Brain is keystone** — migrate FastAPI Brain LAST among FastAPI services
6. **Verification is mandatory** — every file write verified with size + line count + grep spot-check
7. **Sub-milestones within phases** with independent verification; stop at discovery outputs before proceeding
8. **Ken reads scripts before running them** — no prompt-and-go

---

## Phase Sequence

| Phase | Title | Risk | Sessions | Blocks next? |
|---|---|---|---|---|
| 5.0 | Foundation & Prep | Low | 2–3 | Yes |
| 5.1 | Observability Foundation | Low | 1 | Yes |
| 5.2 | Registry Deployment | Low | 1 | Yes |
| 5.3 | Gateway FastAPI | Medium | 1 | No |
| 5.4 | Endpoint nginx + UI | Low-Medium | 1 | No |
| 5.5 | Brain FastAPI | **High** | 2–3 | Yes (for 5.6) |
| 5.6 | Brain workers (Buddy + Executor) | Medium | 1 | No |
| 5.7 | Service-token rotation automation | Low | 1 | No |
| 5.8 | Retirement & Sign-off | Low | 0.5–1 | — |

**Total:** 10–13 sessions over ~2–3 months.

### Deferred (not part of Alpha-5)

- **jarvis-forge dashboard containerization** — Sandbox role currently vacant (per 2026-04-20 handoff)
- **Phase 5c external vault (Infisical / Bitwarden)** — Alpha-6
- **Voice UI / STT / TTS** — still not ported from jarvis-core

---

## Phase Details

### Phase 5.0 — Foundation & Prep

**Goal:** All enabling work before any container lands.

**Deliverables:**
- OrbStack installed on Brain, Gateway, Endpoint (one node at a time, verify per node)
- Unified `get_secret()` consolidated in `jarvis-standards` (F-052) with unit tests
- `~/jarvis/.secrets` split into `~/jarvis/secrets.d/<service>.env` per-service files (F-051)
- `MANIFEST.md` created; preservation scripts read from it (F-053)
- All hardcoded `/Users/xxx` paths removed; `$HOME` expansion everywhere (F-054)
- All native services updated to read from new `secrets.d/` paths
- ADR-0002 exception list verified against actually-deployed services

**Validation:**
- Every native service still running and functional
- `grep -rnE "/Users/[a-z]+" ~/jarvis-alpha/ ~/jarvis-standards/` returns only template files with `{{HOME}}`
- `orb version` succeeds on each node
- `orb list` shows zero containers (expected)
- Preservation tarball test: run script against hardware-swap scenario, verify MANIFEST.md is consulted

**Rollback:** Trivial — old `.secrets` file retained until Phase 5.8 retirement.

**Risks flagged inline:**
- Breaking `get_secret()` breaks everything — unit tests first, migrate callers second
- OrbStack install coordinates with current LaunchAgent port usage — check for contention before enabling

---

### Phase 5.1 — Observability Foundation

**Goal:** Unified logging across native + container surfaces BEFORE anything gets harder to debug.

**Deliverables:**
- Loki + Grafana deployed on Brain as the **first containerized services** (low stakes — new infra, not a migration)
- Fluentbit on Brain tails both macOS unified log AND Docker logs
- Gateway + Endpoint Fluentbit forwarders point at Brain Loki
- Grafana dashboard: per-node, per-service log stream
- Log retention configured (e.g., 30 days hot, 90 days cold on Unraid)

**Why first:** Proves the Compose pattern on services whose failure doesn't break anything else. Gives us working observability before Brain / Gateway migrations when we need it most.

**Validation:**
- Native service logs visible in Grafana (source-tagged correctly)
- Cross-node forwarding works (Gateway → Brain Loki, Endpoint → Brain Loki)
- Log retention + rotation configured
- Dashboard queries return expected results for a test service

**Rollback:** Stop Loki container; native logs continue to flow to macOS unified log (not lost).

---

### Phase 5.2 — Registry Deployment

**Goal:** `registry:2` on Brain, accessible to all nodes via Tailscale.

**Deliverables:**
- `registry:2` Compose service on Brain
- TLS via Tailscale-issued cert for `brain.tail40ed36.ts.net`
- htpasswd authentication per-node (3 entries: `brain-pull`, `gateway-pull`, `endpoint-pull`)
- Per-node credentials in `secrets.d/registry-pull.env`
- Garbage-collection LaunchAgent on Brain (weekly)
- Tag discipline documented: `<service>:YYYY.MM.DD-N` format
- First test image pushed and pulled successfully from all 3 nodes
- osxkeychain credential helper verified on each node (F-060)

**Validation:**
- Push from Air: `docker push brain.tail40ed36.ts.net:5000/test:1`
- Pull from all 3 nodes using node-specific credentials
- Unauthorized pull from Sandbox (if online) correctly rejected
- `cat ~/.docker/config.json` on each node shows `"credsStore": "osxkeychain"`
- Registry logs flowing to Loki (validates Phase 5.1 end-to-end)

**Rollback:** Stop registry container. No services depend on it yet.

---

### Phase 5.3 — Gateway FastAPI (lowest-risk production service)

**Goal:** Prove the pattern on the least-critical production FastAPI service.

**Why Gateway first:**
- Hardware freshly rebuilt 2026-04-20 — clean baseline
- Failure scope limited to cloud routing (Brain → Anthropic/Perplexity/Gemini) — not whole-system
- Pure stateless adapter — no state-migration concerns

**Deliverables:**
- `gateway-fastapi` Dockerfile + multi-arch build
- Image pushed to Brain registry: `brain.tail40ed36.ts.net:5000/gateway-fastapi:2026.XX.XX-1`
- `deploy/gateway/docker-compose.yml` with:
 - Compose `secrets:` stanza for cloud API keys, UniFi creds, service token
 - mTLS certs bind-mounted read-only from `~/jarvis/certs/`
 - `x-` anchor for restart policy and logging
 - Image tag from `deploy/.env`: `${GATEWAY_API_TAG}`
- Blue/green cutover: old LaunchAgent on port 8284, new container on 8283
- Fluentbit log shipping confirmed

**Validation matrix:**
- Brain → Gateway cloud-call end-to-end for all 3 providers (Claude, Perplexity, Gemini)
- UniFi proxy endpoints respond (stubs remain stubs)
- Logs flow to Loki with correct service tag
- Container restarts cleanly after force-kill
- 24h stability window before native LaunchAgent is decommissioned

**Rollback:** Stop container, swap ports back, re-enable LaunchAgent. Cutover is one `docker compose down` and one `launchctl bootstrap`.

---

### Phase 5.4 — Endpoint nginx + UI

**Goal:** Simple static-content service, proves the bind-mount pattern for pre-built artifacts.

**Deliverables:**
- `endpoint-nginx` image (nginx + baked React UI dist, OR separate build artifact bind-mounted)
- `deploy/endpoint/docker-compose.yml`
- Tailscale cert bind-mounted
- Port 4100 blue/green cutover
- Cert-renewal LaunchAgent installed (sends SIGHUP to nginx container)

**Validation:**
- UI loads from `https://jarvis-endpoint.tail40ed36.ts.net:4100`
- PIN gate works
- Proxied Brain API calls succeed
- No broken assets in browser console
- SIGHUP test: manually trigger renewal, verify zero-downtime cert swap

**Rollback:** Stop container, re-enable native nginx LaunchAgent.

---

### Phase 5.5 — Brain FastAPI (HIGHEST RISK — keystone service)

**Goal:** Containerize the most critical service while everything else is already migrated.

**Deliverables:**
- `brain-fastapi` Dockerfile + build
- `deploy/brain/docker-compose.yml` with:
 - `extra_hosts: ["host.docker.internal:host-gateway"]`
 - Postgres connection → `postgresql://...@host.docker.internal:5432/jarvis_alpha`
 - Ollama → `http://host.docker.internal:11434`
 - Temporal gRPC → `host.docker.internal:7233`
 - Compose secrets for all 10+ secrets per ADR-0003
 - JWT private key bind-mounted read-only
 - Healthcheck on `/health` endpoint
 - `depends_on` cannot gate on native services; use in-app startup retry instead
- Blue/green: native Brain temporarily moved to a non-production fallback port such as 8188; container takes production port 8186. Do **not** use 8187; Brain reserves it for `jarvis-family`.

**Validation matrix (ALL must pass):**
- PIN auth works end-to-end
- `/v1/ask` round-trip including Ollama local routing (GPU access via host.docker.internal)
- `/v1/tasks/graphs` CRUD
- Buddy events polling from UI
- Memory routes (embeddings, RLS context, tier promotion)
- UniFi proxy → Gateway (cross-node container-to-container)
- Cost aggregation from `/api/costs/report`
- `/v1/home/summary`
- `/v1/mesh/status`
- Cross-node service token auth (Gateway → Brain, Endpoint → Brain)
- JWT signing still works (key bind-mount correct)
- Postgres RLS policies enforced from container context
- Working memory eviction and episodic promotion still runs

**Risks flagged inline:**
- `host.docker.internal` must resolve — verify with `docker run ... curl host.docker.internal:5432`
- Startup race: container starts before Postgres is ready → repeated crash-restart. Mitigate with healthcheck + in-app backoff retry to Postgres
- JWT key rotation while container running: container must re-read file on signal or restart (test explicitly)
- `set_config()` transaction-scoped GUC behavior — verify RLS context still works from container Postgres connection
- Stale `__pycache__` in image builds — clear during Docker build step

**Rollback:** Stop container, swap ports, re-enable native LaunchAgent. This is the phase where rollback discipline matters most.

---

### Phase 5.6 — Brain workers (Buddy + Executor)

**Goal:** Containerize background workers. Depends on Brain FastAPI container being stable (24h+).

**Deliverables:**
- `buddy-agent` container
- `taskgraph-executor` container
- Shared Compose stanza or per-service files in `deploy/brain/docker-compose.yml`
- Internal health endpoints for Docker healthcheck
- Postgres NOTIFY channel subscription works from container (executor)

**Validation:**
- Buddy emits `alpha_buddy_events` rows on schedule (60s loop)
- TaskGraph recovery fires on startup
- Working memory eviction runs (24h cycle — test with shortened TTL)
- Episodic → semantic promotion runs
- `graph_submitted` NOTIFY channel delivers events to executor

**Rollback:** Stop containers, re-enable LaunchAgents (`com.jarvis.alpha.buddy`, `com.jarvis.alpha.executor`).

---

### Phase 5.7 — Service-token rotation automation

**Goal:** Close F-023 for internal service tokens (Phase 5b of ADR-0003).

**Deliverables:**
- Rotation LaunchAgent on Brain (stubs exist: `com.jarvis.alpha.rotate.brain_service`, `rotate.buddy`)
- Equivalent on Gateway, Endpoint
- Rotation script:
 1. Generate new RS256-signed service token
 2. Write new token to `secrets.d/<service>.env`
 3. Signal consuming container (SIGHUP OR `docker compose restart <service>`)
 4. **Grace period 30s**: old + new both valid simultaneously
 5. Remove old token from valid set
- Documented runbook for emergency rotation

**Validation:**
- Force rotation during live traffic → zero auth failures observed in Grafana
- Old token rejected after grace period
- Next-scheduled rotation (24h cron) completes cleanly without manual intervention
- Alert fires on rotation failure

**Rollback:** Disable rotation LaunchAgent. Manual rotation via runbook.

---

### Phase 5.8 — Retirement & Sign-off

**Goal:** Remove dual paths, formalize completion.

**Deliverables:**
- `launchctl bootout` all now-redundant native LaunchAgents
- Plist templates retained in git (emergency rollback path) but excluded from `install_launchagents.py` default install
- `install_launchagents.py --node <n>` filter updated per ADR-0002 exception list
- Architecture Review V2 §3 (node topology) updated to reflect containerized services
- Architecture Review V2 §4 (service state) updated so native/container placement matches the Phase 5.8 end state
- Alpha-5 sign-off handoff doc

**Sign-off criteria:**
- All containerized services running in OrbStack across Brain / Gateway / Endpoint
- All native services match ADR-0002 exception list exactly
- All secrets in `secrets.d/` per-service files
- `MANIFEST.md` current, preservation scripts consume it
- Rotation LaunchAgent active on all 3 nodes
- Observability unified (Loki + Grafana)
- Registry + GC LaunchAgent running on Brain
- Cert-renewal LaunchAgent running on all 3 nodes (staggered)
- F-051 through F-055 closed; F-058 through F-061 closed
- Alpha-5 handoff doc written

---

## Service Placement Grid

### Native (LaunchAgent) — ADR-0002 exhaustive exception list

| Service | Node | Justification |
|---|---|---|
| Postgres 16 + pgvector + extensions | Brain | Stateful, I/O-sensitive, extensions, upgrade path |
| SQLite (forge + module-local DBs) | Sandbox + any | File-based state — no runtime to containerize |
| Ollama (llama3.1:8b, qwen2.5-coder:7b) | Brain | Metal GPU access — non-negotiable |
| Temporal server + UI | Brain | Stateful orchestrator, bound to native Postgres |
| Tailscale daemon | All | Kernel-level networking |
| Voice UI / STT / TTS (future) | Endpoint | Audio I/O hardware access |

### Containerized (OrbStack + Compose) — Alpha-5 scope

| Service | Node | Phase |
|---|---|---|
| FastAPI Gateway | Gateway | 5.3 |
| nginx + React UI | Endpoint | 5.4 |
| FastAPI Brain | Brain | 5.5 |
| Buddy agent | Brain | 5.6 |
| TaskGraph executor | Brain | 5.6 |
| Loki + Grafana | Brain | 5.1 |
| Fluentbit | All | 5.1 |
| `registry:2` | Brain | 5.2 |

---

## Forge Backlog

New F-IDs introduced this session. Append to `~/jarvis-forge/memory/seed_backlog.py` on Sandbox when hardware is reassigned.

### Phase 5.0 (Foundation)

| ID | Title | Priority | Blocks |
|---|---|---|---|
| F-051 | Split `.secrets` into `secrets.d/` per-service directory | P1 | All service migrations |
| F-052 | Consolidate `get_secret()` into `jarvis-standards` (closes F-034) | P1 | F-051 must follow |
| F-053 | Create `MANIFEST.md` + wire preservation scripts to read it | P1 | Preservation reliability |
| F-054 | Remove hardcoded `/Users/xxx` paths; use `$HOME` expansion | P1 | Hardware-swap reliability |

### Phase 5.1–5.2 (Infrastructure)

| ID | Title | Priority | Blocks |
|---|---|---|---|
| F-058 | `registry:2` deployment on Brain with TLS + htpasswd + GC LaunchAgent | P1 | Phase 5.3+ |
| F-059 | `deploy/.env` centralized image-tag scheme + rollback procedure doc | P2 | Phase 5.3+ |
| F-060 | Verify `credsStore: osxkeychain` on each node post-OrbStack install | P2 | Phase 5.2 |

### Phase 5.3–5.7 (Services)

| ID | Title | Priority | Blocks |
|---|---|---|---|
| F-055 | LaunchAgent service-token rotation with grace period | P2 | F-023 closure |
| F-061 | Cert-renewal LaunchAgent on each node with staggered schedule | P2 | Alpha-5 sign-off |

### Alpha-6+ (deferred)

| ID | Title | Priority |
|---|---|---|
| F-056 | Evaluate Infisical vs Bitwarden Secrets Manager + deploy | P3 |
| F-057 | SOPS + age for encrypted-config-in-git (optional complement) | P3 |
| F-062 | Migrate registry pull auth to token-based (when Phase 5c vault lands) | P3 |

---

## Validation Criteria

### Per-phase gates

Every phase must pass ALL of these before proceeding to the next:

1. **Functional validation** — Phase-specific validation matrix (see Phase Details)
2. **Observability validation** — Logs flowing correctly from new services into Loki
3. **Performance validation** — No regressions vs native baseline (latency, memory, CPU)
4. **Stability validation** — 24h soak minimum before decommissioning native equivalent
5. **Rollback validation** — Verified that rollback procedure works on a test scenario

### Cross-phase invariants

These must hold at every phase boundary:

- Native Postgres performance: ≥ pre-Alpha-5 baseline (2–4× faster than any Docker'd alternative)
- Ollama Metal GPU access: preserved (verify with `ollama ps` + inference latency benchmark)
- 79% local routing target: preserved
- Zero hardcoded `/Users/xxx` paths anywhere in jarvis-alpha or jarvis-standards
- MANIFEST.md present and up to date
- All secrets paths chmod 600

---

## Rollback Procedures

### Per-service container rollback (Phases 5.3–5.6)

```
# On affected node
docker compose -f /path/to/docker-compose.yml down <service>
# Re-enable native LaunchAgent
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.jarvis.alpha.<service>.plist
# Verify health
curl -sk https://<node>.tail40ed36.ts.net:<port>/health
```

### Per-phase rollback decision tree

- **Phase 5.0 / 5.1 / 5.2:** Stop new containers, revert secrets.d changes via git, restore old `.secrets` from backup
- **Phase 5.3–5.6:** Per-service rollback procedure above; native LaunchAgent retained through Phase 5.8
- **Phase 5.7:** Disable rotation LaunchAgent, manual rotation via runbook
- **Phase 5.8:** By this point, retirement is done; rollback would require re-installing retired LaunchAgents from git history

### Emergency break-glass

If Brain FastAPI container (Phase 5.5) causes cascading failure:

1. `docker compose -f ~/jarvis-alpha/deploy/brain/docker-compose.yml stop brain-api`
2. `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.jarvis.alpha.brain.plist`
3. Update DNS / internal routing to old port if needed
4. Investigate in Loki + post-mortem before retrying

---

## Out of Scope

Explicitly deferred, with target future phases:

| Item | Deferred to | Reason |
|---|---|---|
| jarvis-forge dashboard containerization | Post-Alpha-5 | Sandbox role currently vacant |
| External vault (Infisical/Bitwarden) | Alpha-6 | Bootstrap complexity during already-disruptive migration |
| Kubernetes introduction | Alpha-7+ if ever | Not needed at 3-node scale |
| Postgres containerization | Never (per ADR-0002) | Performance + upgrade-path cost |
| Ollama containerization | Never (per ADR-0002) | Metal GPU access |
| Voice UI / STT / TTS | Post-Alpha-5 | Not yet ported from jarvis-core |
| Mobile iOS app | Post-Alpha-5 | Alpha stability first |

---

## Risks and Mitigations

### Architectural

| Risk | Impact | Mitigation |
|---|---|---|
| Observability split (native log vs Docker log) makes debugging harder | High | Phase 5.1 unified Loki deployed BEFORE any service migrates |
| Registry single-point-of-failure for new deploys | Medium | Image cache on each node; restart-on-failure policy; registry itself is stateless |
| `host.docker.internal` fails to resolve on Brain | High | Verify in Phase 5.0 with test container; OrbStack supports this natively |
| Native exception list drifts ("just one more native service") | Medium | ADR amendment required for changes; documented and visible in ADR-0002 |

### Operational

| Risk | Impact | Mitigation |
|---|---|---|
| `get_secret()` consolidation breaks existing callers | High | Unit tests first in Phase 5.0; migrate callers incrementally |
| Drift in `~/.docker/config.json` across nodes | Medium | F-060 verification step; documented in MANIFEST |
| Cert renewal all nodes at once causes brownout | Medium | Staggered schedule (Brain 02:00, Gateway 02:30, Endpoint 03:00) |
| Container startup race before Postgres ready | High | Healthcheck + in-app backoff retry; NOT `depends_on` since Postgres is native |

### Rollback-specific

| Risk | Impact | Mitigation |
|---|---|---|
| Native LaunchAgent removed before 24h soak complete | Critical | Phase 5.8 retirement only after sign-off criteria met |
| Plist templates deleted prematurely | High | Templates retained in git post-retirement; `install_launchagents.py` filter changes, files stay |
| Secrets file split creates invisible regression | High | Unit tests for `get_secret()`; functional validation on every service post-migration |

---

## References

- **ADR-0002:** State Native, Compute Containerized
- **ADR-0003:** Progressive Secrets Management
- **ADR-0004:** Alpha-5 Execution Standards
- **Session transcripts:** 2026-04-20 (Gateway M1→M4 swap), 2026-04-21 (Alpha-5 planning)
- **Perplexity validations:** Q2 state/compute pattern, Q3 secrets pattern, Q4-sub-decisions (registry/compose/cert/auth)
- **Prior handoffs:** `HANDOFF_2026-04-20.md`, `HANDOFF_launchagent_templating.md`
- **Architecture Review V2:** canonical amended architecture review; update §3 and §4 again during Phase 5.8 sign-off to reflect actual containerized services

---

*End of Alpha-5 Migration Plan — ready for Phase 5.0 kickoff.*
