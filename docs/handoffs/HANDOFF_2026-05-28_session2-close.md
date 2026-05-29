# HANDOFF — Session 2 Close — 2026-05-28

**Status:** Session 2 complete. 5 PRs merged. Repo at `6be4ca4`.
**Previous handoff:** `HANDOFF_2026-05-28_session1-close.md` (opened this session)
**Next session:** Session 2.5 or 3 — scope in §5

---

## 1. Headline

5 PRs merged in one session. Closed AUDIT-7, 8, 9, 12. Reclassified AUDIT-6 OPEN → 🟡 PARTIAL with corrected root cause. Filed TD-AGENT-CATEGORIZATION + several P3 TDs.

| PR | Title | Merge SHA | Closes |
|---|---|---|---|
| #155 | `chore(deps): add mypy + pytest-cov to dev deps (AUDIT-12)` | `9b361e5` | AUDIT-12 |
| #156 | `docs(observability): label taxonomy + AUDIT-6 reclass PARTIAL` | `2e8d32f` | AUDIT-6 (docs) |
| #157 | `feat(ops): jarvisalpha_rollback.sh + ADR-0014 (AUDIT-7)` | `6a52672` | AUDIT-7 |
| #158 | `fix(middleware): sync rate-limit docstring to constant (AUDIT-9)` | `c516b52` | AUDIT-9 |
| #159 | `fix(health): extend BRAIN_AGENTS to 11 always-on (AUDIT-8)` | `6be4ca4` | AUDIT-8 |

Plus: SSH shortcuts added to Sandbox `~/.ssh/config` (`jarvis-brain`, `jarvis-gateway`, `jarvis-endpoint` Host blocks). No PR — local config. Backup at `~/.ssh/config.bak.20260528_183604`.

---

## 2. Audit landscape — post-Session 2

| Audit | Status | Detail |
|---|---|---|
| AUDIT-1 | ✅ CLOSED | Backups (PR #152, Session 1) |
| AUDIT-2 | ❌ OPEN | Untested modules — multi-session push, no Session 2 work |
| AUDIT-3 | ❌ OPEN | Deep `/health/ready` probe — deferred to Session 2.5/3 |
| AUDIT-4 | 🟢 GUARD-LANDED | httpx invariant (PR #153, Session 1.5) |
| AUDIT-5 | 🟡 PARTIAL | Plist templating — Alpha-5 Phase 5.0 |
| AUDIT-6 | 🟡 PARTIAL | Reclassified this session: pipeline live, Fluentbit JSON parser missing |
| AUDIT-7 | ✅ CLOSED | `jarvisalpha_rollback.sh` + ADR-0014 (PR #157, this session) |
| AUDIT-8 | ✅ CLOSED | BRAIN_AGENTS 3 → 11 always-on (PR #159, this session) |
| AUDIT-9 | ✅ CLOSED | rate-limit docstring sync (PR #158, this session) |
| AUDIT-10 | ❌ OPEN | V2 → V3 doc refresh — Session 4 |
| AUDIT-11 | ❌ OPEN | `thread_memory_extracts` decision — Session 4 |
| AUDIT-12 | ✅ CLOSED | mypy + pytest-cov dev deps (PR #155, this session) |

**Closed:** 4 newly closed + 1 reclassified PARTIAL. **Net gap reduction:** 5 audit items advanced.

---

## 3. Per-PR detail

### PR #155 — AUDIT-12: mypy + pytest-cov dev deps

**Files changed:**
- `pyproject.toml` (2 lines added in `[dependency-groups].dev`)
- `uv.lock` (refreshed)

**Behavior:** None — dev-deps only. Foundation for Session 2 type-checking + coverage work.

**Versions installed:**
- `mypy>=1.11` (resolved to 2.1.0)
- `pytest-cov>=5.0` (resolved to 7.1.0)

### PR #156 — AUDIT-6 reclass + LABEL_TAXONOMY.md

**Files changed:**
- NEW: `docs/observability/LABEL_TAXONOMY.md` (170 lines, 11 sections)
- MODIFIED: `docs/audit/GAP_ANALYSIS_v2.md` (4 surgical edits — lines 24, 80, 106, 152)

**Behavior:** None — docs only.

**Critical reframe:** Original AUDIT-6 evidence (`logging_config.py:100-102 — stdout-only handler`) was a misread of intentional architecture. Discovery (Phase 2a) confirmed:
- Brain Fluentbit running (PID 84515) and shipping ~14k lines/hr to Loki
- Endpoint Fluentbit also shipping
- The defect is missing JSON parser in `~/fluent-bit/fluent-bit.yaml` — `label_keys: $service,$level` resolve against unparsed `{"log":...}` envelope → all logs collapse to `service_name=unknown_service`

**LABEL_TAXONOMY.md content:**
- Design principles (low cardinality, JSON-parse-before-label, static-fact rule)
- Required labels: `node`, `service`, `level` (3 only — max 400 streams fleet-wide)
- Service inventory per node: Brain (14), Gateway (1), Endpoint (3), Sandbox (2)
- Naming convention: `<node>_<role>` snake_case (with current emit-vs-target drift note)
- Migration path for Phase 4c
- Anti-patterns (don't label trace_id, request_id, user_id, http_path, etc.)
- Known gaps snapshot

### PR #157 — AUDIT-7: jarvisalpha_rollback.sh + ADR-0014

**Files changed:**
- NEW: `scripts/jarvisalpha_rollback.sh` (606 lines, executable)
- NEW: `docs/adr/ADR-0014-rollback-policy.md` (79 lines)

**Behavior:** New rollback capability. Forward operations unchanged.

**Script modes:**
- `--dry-run` (default) — print plan, no actions
- `--open` — create revert PR via `gh pr revert`, exit
- `--full` — open + watch CI + self-merge + run `jarvisalpha_deploy.sh`

**Safety rails:**
- `--full` requires explicit `--yes`
- DB migration detection HALTs unless `--db-restored` overrides
- Backup recency check (36h max age) unless `--skip-backup-check` overrides
- Symmetric to deploy: same eventing (`##EVT##`), same `mm_notify` channels, same failure_box pattern

**ADR-0014 decision summary:** PR-revert is the ONLY rollback path. Force-push is blocked at two layers (pre-commit hook + branch protection); no emergency-bypass mode by design. The 5-minute CI floor is acceptable for personal/family AI.

**Smoke test result:** `--dry-run` against PR #156 worked correctly. Caught a real bug during testing: original script used `BACKUP_SSH_*` (Brain push creds); Sandbox has `RESTORE_SSH_*` (read-only pull creds). Fixed in the same PR.

### PR #158 — AUDIT-9: rate-limit docstring sync

**Files changed:**
- `brain/middleware/rate_limit_middleware.py` (1 line — docstring only)

**Behavior:** None — docstring fix.

**Detail:** `MAX_REQUESTS = 300` (set in commit `3e3b1e02` on 2026-04-06 with msg "bump rate limit to 300 req/min — React Query parallel fetches exceed 100"). Docstring still said "100 req/min" from original implementation. Fixed to "300 req/min."

### PR #159 — AUDIT-8: BRAIN_AGENTS extension

**Files changed:**
- `brain/routes/health.py` (BRAIN_AGENTS list expanded, +11 lines)
- `docs/audit/GAP_ANALYSIS_v2.md` (+1 line — TD-AGENT-CATEGORIZATION filed)

**Behavior:** `/health/agents` endpoint now reports on 11 agents instead of 3. Endpoint logic unchanged.

**New BRAIN_AGENTS (11 always-on):**

```python
BRAIN_AGENTS = [
    # Alpha core
    "com.jarvis.alpha.brain",
    "com.jarvis.alpha.buddy",
    "com.jarvis.alpha.executor",
    "com.jarvis.alpha.watchdog",
    # Observability
    "com.jarvis.alpha.fluentbit",
    "com.jarvis.alpha.loki",
    # Temporal
    "com.jarvis.alpha.temporal.server",
    "com.jarvis.alpha.temporal.ui",
    "com.jarvis.alpha.temporal.worker",
    # Telemetry
    "com.jarvis.alpha.power.brain",
    # Infrastructure
    "com.jarvis.ollama",
]
```

**Excluded as scheduled (not always-on):**
- `com.jarvis.alpha.pg_backup` (StartCalendarInterval — nightly 02:30)
- `com.jarvis.alpha.rotate.brain_service` (StartInterval=86400s)
- `com.jarvis.alpha.rotate.buddy` (StartInterval=86400s)
- `com.jarvis.alpha.school-email` (StartCalendarInterval)

Each verified via plist inspection (`KeepAlive` vs `StartCalendarInterval`/`StartInterval`).

---

## 4. Discovery surprises worth preserving

Future-Ken: these saved diagnostic time once; bake them in to avoid re-discovery.

### 4.1 Loki/Fluentbit ARE shipping (not "inactive")

The Session 1 handoff said AUDIT-6 = "plists exist, inactive." Phase 2a discovery proved this was wrong:
- Fluentbit PID 84515 running 3+ days
- Loki PID 84530 running 3+ days
- 14,683 log lines from Brain in last 1h
- Endpoint also shipping

The audit was right that LABELS are broken; wrong that the SHIPPER was inactive.

**Don't repeat this misread.** When evaluating observability, distinguish "shipper alive" from "shipper useful." Pipeline can be running while data is unqueryable.

### 4.2 BACKUP_SSH_* vs RESTORE_SSH_* split

**Brain has push credentials** (`BACKUP_SSH_HOST`, `BACKUP_SSH_USER`, `BACKUP_SSH_KEY`, `BACKUP_SSH_TARGET_DIR`) at `~/jarvis/.secrets` — used by `pg_backup_alpha.sh` to write nightly dumps to Unraid.

**Sandbox has pull credentials** (`RESTORE_SSH_HOST`, `RESTORE_SSH_USER`, `RESTORE_SSH_KEY`, `RESTORE_SSH_SOURCE_DIR`) at `~/.secrets` — used by `restore_drill_alpha.sh` to read dumps for verification.

Any Sandbox-driven script that touches Unraid backups must use `RESTORE_SSH_*` (the read-only creds present there), NOT `BACKUP_SSH_*` (which don't exist on Sandbox).

The rollback script (`jarvisalpha_rollback.sh`) demonstrates the correct pattern — see `check_backup_recency()`.

### 4.3 `power_sampler_brain.plist` filename mismatch

Plist filename is `power_sampler_brain.plist` (underscored, Linux-style), but its internal `Label` is `com.jarvis.alpha.power.brain` (dotted, Alpha convention). launchctl tracks by Label, so BRAIN_AGENTS list entry must use the Label form.

This is a cosmetic TD — eventually rename the plist file to match the convention (`com.jarvis.alpha.power.brain.plist`). Low priority.

### 4.4 Native `gh pr revert` exists

Don't write a manual `git revert <SHA> → new branch → gh pr create` flow. `gh pr revert <number>` does it natively. The rollback script uses this.

### 4.5 Force-push to `main` is blocked at two layers

- Pre-commit hook `JARVIS force-push block on protected refs` (entry: `.jarvis-hooks/pre-push`) — local enforcement, visible as `JARVIS force-push block on protected refs........Passed` in every `git push` output
- GitHub branch protection on `main` (required status checks = 6, no force-push allowed)

ADR-0014 documents the implication: no "emergency direct-push" rollback mode is possible without defeating both protections — a security regression. PR-revert is the only path.

### 4.6 SSH shortcut user defaults

`ssh jarvis-brain` shorthand previously defaulted to user `jarvissand` (Sandbox's user) and failed. Fix (PR-less, Phase 1a) added explicit `User jarvisbrain` / `User gate` / `User jarvisendpoint` to `~/.ssh/config` Host blocks. Endpoint block was preserved (had deploy-key pin for `jarvisalpha_deploy.sh`).

Brain + Gateway blocks intentionally OMIT `IdentityFile` because default identity selection (`~/.ssh/id_*`) works for those. If multi-key auth fatigue emerges, pin explicitly. Tracked as informal TD.

---

## 5. Outstanding for Session 2.5/3

These were in original Session 2 scope but deferred per Option A+B decision.

### 5.1 AUDIT-3 — Deep `/health/ready` probe

**Locked design (Q1 from architecture review):**
- New endpoint `/health/ready` (do NOT modify existing `/health` — backward-compat for UI Home, Buddy, external monitors)
- Aggregated JSON body with per-check status: DB pool, Ollama generate, Temporal client
- HTTP 200 if all critical pass; HTTP 503 on any critical fail
- ~200ms per-check timeout budget (`asyncio.wait_for(check, timeout=0.2)`)

**Pre-flight verification needed before deploy:**
- nginx Endpoint proxy behavior on backend 503 (does it convert to user-visible error page?)
- Brain restart safety (mitigated by leaving `/health` shallow as fallback)

**Estimate:** 1.5 hrs

### 5.2 AUDIT-6 Phase 4c — Fluentbit JSON parser fix

**Locked design (from LABEL_TAXONOMY.md §7):**
1. Edit `~/jarvis-alpha/fluent-bit/fluent-bit.yaml.template`
2. Add `parsers:` block defining `json_log` (format: `json`, `time_key: ts`)
3. Add `parser: json_log` to each `tail` input
4. Render via `jarvisalpha_pull.sh` on Brain → reload Fluentbit
5. Verify via `/loki/api/v1/label/service/values` returns multiple values (not `["unknown_service"]`)

**Risk:** Fluentbit reload — observability blind spot during reload. Mitigated by quick reload (<5s).

**Estimate:** 1 hr

### 5.3 New TDs from Session 2 (low priority queue)

| TD | Source | Priority |
|---|---|---|
| TD-AGENT-CATEGORIZATION | Phase 4-1b (PR #159) — filed in GAP_v2 §2b | P2 |
| TD-SSH-IDENTITY-PIN | Phase 1a (informal) | P3 |
| TD-POWER-PLIST-RENAME | Phase 4-1b discovery | P3 |
| TD-ENDPOINT-FLUENTBIT-AUDIT | Phase 2a — config unverified | P2 |
| TD-GATEWAY-SHIPPER | Phase 2a — Gateway has no Fluentbit | P2 |
| TD-SANDBOX-SHIPPER | Phase 2a — Sandbox has no Fluentbit | P2 |
| TD-LABEL-TAXONOMY-STANDARDS-MIGRATION | LABEL_TAXONOMY.md §10 | P3 |

---

## 6. Architecture decisions locked this session

### 6.1 ADR-0014 — Rollback policy

- PR-revert is the ONLY rollback path
- No emergency direct-push mode (force-push is blocked by design)
- DB migration rollback is OUT OF SCOPE — operator-asserted via `--db-restored`
- Single script handles all three modes (dry-run / open / full)

### 6.2 LABEL_TAXONOMY (LABEL_TAXONOMY.md)

- 3 labels only: `node`, `service`, `level`
- Max 400 streams fleet-wide (4 nodes × 20 services × 5 levels)
- High-cardinality fields stay in JSON body (trace_id, request_id, user_id, paths)
- Service naming: `<node>_<role>` snake_case (target — current Python emits `alpha_*`)
- JSON parsing MUST happen in Fluentbit before label extraction

### 6.3 Agent categorization (Phase 4-1b)

- `BRAIN_AGENTS` = always-on only (KeepAlive=true)
- Scheduled agents (StartCalendarInterval, StartInterval) tracked separately (TD-AGENT-CATEGORIZATION)
- Verify via plist inspection, NOT runtime PID check (idle scheduled agents have PID=- legitimately)

### 6.4 SSH config conventions (Phase 1a)

- Explicit `HostName <FQDN>` even when Tailscale Magic DNS works (defense in depth)
- `User <correct user>` in Host block (not default selection)
- Preserve existing `IdentityFile` pins (Endpoint had deploy-key; do not overwrite)

---

## 7. §8 Resume sequence — for next session opening

Run these on Air or Sandbox at session open to verify state:

### 7.1 PR + audit state

```bash
gh pr view 155 --repo kphaas/jarvis-alpha --json number,state,mergedAt,mergeCommit
gh pr view 156 --repo kphaas/jarvis-alpha --json number,state,mergedAt,mergeCommit
gh pr view 157 --repo kphaas/jarvis-alpha --json number,state,mergedAt,mergeCommit
gh pr view 158 --repo kphaas/jarvis-alpha --json number,state,mergedAt,mergeCommit
gh pr view 159 --repo kphaas/jarvis-alpha --json number,state,mergedAt,mergeCommit
```

Expected: all MERGED.

### 7.2 Per-node HEAD sync

```bash
ssh jarvis-brain 'cd ~/jarvis-alpha && git rev-parse --short HEAD'
ssh jarvis-gateway 'cd ~/jarvis-alpha && git rev-parse --short HEAD'
ssh jarvis-endpoint 'cd ~/jarvis-alpha && git rev-parse --short HEAD'
cd ~/jarvis-alpha && git rev-parse --short HEAD  # Sandbox
```

Expected: all `6be4ca4` or later. If any node behind, run `bash scripts/jarvisalpha_pull.sh` on that node.

### 7.3 Always-on LaunchAgents

```bash
ssh jarvis-brain 'launchctl list | grep com.jarvis.alpha'
```

Expected PIDs (non-`-`) for: brain, buddy, executor, fluentbit, loki, power.brain, temporal.{server,ui,worker}, watchdog. Plus `com.jarvis.ollama`.

PID=`-` expected for: pg_backup, rotate.{brain_service,buddy}, school-email (scheduled).

### 7.4 Backup pipeline

```bash
ssh -i ~/.ssh/jarvis_alpha_backup root@192.168.30.10 \
  'ls -lht /mnt/user/Backups/jarvis-alpha/dumps/jarvis_alpha_*.dump.gpg | head -3'
```

Expected: ≥1 dump from last 24h.

### 7.5 Loki ingest (should still be live)

```bash
ssh jarvis-brain 'curl -sS http://127.0.0.1:3100/ready'
ssh jarvis-brain 'curl -sS "http://127.0.0.1:3100/loki/api/v1/labels"'
```

Expected: `HTTP 200`; labels include `node` and `service_name`.

**Until Phase 4c Fluentbit parser fix lands, `service_name` will still be `unknown_service`.**

### 7.6 Rollback script smoke (verify still works)

```bash
cd ~/jarvis-alpha
bash scripts/jarvisalpha_rollback.sh 159 --dry-run
```

Expected: prints plan box for PR #159, exit 0, no actions taken.

---

## 8. Open questions for next session

1. **Order of next sub-phases:** AUDIT-3 (`/health/ready`) first, or AUDIT-6 Phase 4c (Fluentbit parser) first?
   - AUDIT-3 = bigger code change (new endpoint) but isolated to Brain
   - AUDIT-6 Phase 4c = config-only but observability blackout during reload
   - **Suggest AUDIT-6 Phase 4c first** — lower risk, lights up LABEL_TAXONOMY work that's already merged

2. **nginx upstream 503 behavior** — needs pre-verification before AUDIT-3 deploy. How to test cheaply?
   - Option A: read nginx config for `proxy_intercept_errors` setting
   - Option B: spin up mock backend on Brain that returns 503, curl through Endpoint nginx, observe behavior
   - Option C: deploy with feature flag, observe in production

3. **AUDIT-2 (untested modules)** — parallel multi-session push or focused single session?
   - GAP_v2 said "multi-session push" — likely deserves its own thread, not bundled with Phase 4 work

4. **AUDIT-5 (plist templating)** — when does Alpha-5 Phase 5.0 kick off?
   - Currently 2 of 20 plists templated. Substantial work.

5. **school-email scheduling intent** — should it migrate to always-on (with periodic-fetch logic inside) or stay scheduled?
   - Currently classified as scheduled via plist. Confirm operational intent.

---

## 9. Quick reference

### Commit SHAs

| Item | SHA |
|---|---|
| Session 2 open (origin/main) | `8a65d85` |
| Post-PR #155 | `9b361e5` |
| Post-PR #156 | `2e8d32f` |
| Post-PR #157 | `6a52672` |
| Post-PR #158 | `c516b52` |
| Post-PR #159 (Session 2 close) | `6be4ca4` |

### Key files (new this session)

| Path | Purpose |
|---|---|
| `docs/observability/LABEL_TAXONOMY.md` | Loki label schema |
| `docs/adr/ADR-0014-rollback-policy.md` | Rollback policy |
| `scripts/jarvisalpha_rollback.sh` | Rollback executable |
| `docs/handoffs/HANDOFF_2026-05-28_session2-close.md` | This document |
| `~/.ssh/config` (Sandbox) | Host blocks for jarvis-{brain,gateway,endpoint} |

### Modified files

| Path | Change |
|---|---|
| `pyproject.toml` | +2 dev deps (mypy, pytest-cov) |
| `docs/audit/GAP_ANALYSIS_v2.md` | 4 AUDIT-6 reclass edits + TD-AGENT-CATEGORIZATION added |
| `brain/middleware/rate_limit_middleware.py` | docstring sync (300 req/min) |
| `brain/routes/health.py` | BRAIN_AGENTS extended 3 → 11 |

### Resume command (one-liner)

From Sandbox:

```bash
cd ~/jarvis-alpha && git pull --ff-only && git rev-parse --short HEAD && \
  ssh jarvis-brain 'cd ~/jarvis-alpha && git rev-parse --short HEAD' && \
  ssh jarvis-gateway 'cd ~/jarvis-alpha && git rev-parse --short HEAD' && \
  ssh jarvis-endpoint 'cd ~/jarvis-alpha && git rev-parse --short HEAD'
```

Should print `6be4ca4` four times.

---

*End of HANDOFF_2026-05-28_session2-close.md*
