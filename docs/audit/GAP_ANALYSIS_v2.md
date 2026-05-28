# GAP_ANALYSIS_v2 — Post Session 1 + 1.5

**Date:** 2026-05-28
**Predecessor:** `ALPHA_AUDIT_SUMMARY` (2026-05-27, audit at `ebf06d5`) — the
original audit deliverables were written to `/tmp/alpha_audit_2026-05-27/` and
have since been lost when `/tmp` aged out. This document re-derives every
file:line claim against current main on disk; the original audit text was
re-supplied by Ken into the session that produced this doc.
**Main HEAD:** `7037ab1` (PR #153 squash, "test(security): static guard — Brain no public egress")
**Scope:** AUDIT-1..12 from the original audit + TDs surfaced during Session 1
backup work and Session 1.5 httpx guard work.

---

## 1. Audit Findings — Status Matrix

| ID | Finding | Original Sev | Status | Evidence (current main) | Closing PR / Tracking |
|---|---|---|---|---|---|
| AUDIT-1 | No DB backup automation | P0 | ✅ CLOSED | `scripts/pg_backup_alpha.sh`, `scripts/preflight_brain_backup.sh`, `scripts/restore_drill_alpha.sh` present; LaunchAgents `com.jarvis.alpha.pg_backup` (Brain nightly 02:30) + `com.jarvis.alpha.restore_drill` (Sandbox Sun 03:30) loaded | PR #152, ADR-0013 |
| AUDIT-2 | ~80% of brain modules untested | P0 | ❌ OPEN | `find brain -name '*.py'` = 135; `find tests -name 'test_*.py'` = 44 (one test file may cover multiple modules; structural ratio unchanged) | TD-COV-1 (multi-session push) |
| AUDIT-3 | `/health` does not probe DB / Ollama / Temporal | P1 | ❌ OPEN | `brain/routes/health.py:127-129` returns `{"status":"ok","node":"brain","service":"jarvis-alpha"}` only — no dependency probe | Session 2 candidate |
| AUDIT-4 | Possible Brain → public internet violation (V2 §1) | P1 | 🟢 GUARD-LANDED | `tests/test_no_external_urls.py` (PR #153, 319 lines) enforces invariant across all `brain/*.py`. **5 real violations documented as strict-xfail TDs**: see TD-S15-1..4 below | PR #153, TD-S15-1..4 |
| AUDIT-5 | 15/20 LaunchAgent plists hardcode `/Users/<user>/` | P1 | 🟡 PARTIAL | `ls launchagents/*.template.plist` = 7 (was 5 pre-Session 1); `ls launchagents/*.plist` (non-template) = 15. New work added 2 templates; the 15 legacy hardcoded plists remain | Alpha-5 Phase 5.0 |
| AUDIT-6 | Loki + Fluentbit plists present, shippers inactive | P1 | ❌ OPEN | `common/jarvis_common/logging_config.py:100-102` — `stdout_handler = logging.StreamHandler(sys.stdout)` is the only handler attached; no Loki/Fluentbit shipper code path. `brain/config/logging_config.py` is a re-export shim | Session 2 candidate |
| AUDIT-7 | No rollback script | P1 | ❌ OPEN | `scripts/jarvisalpha_rollback.sh` and `scripts/jarvisalpha_revert.sh` do not exist. `scripts/jarvisalpha_deploy.sh` remains forward-only (Phase 6 of Session 1 deploy confirmed via `gh pr merge --squash` revert path only) | Session 2 candidate |
| AUDIT-8 | `/health/agents` only surfaces 3 of 8+ LaunchAgents | P2 | ❌ OPEN | `brain/routes/health.py:19-25` — `BRAIN_AGENTS = ["com.jarvis.alpha.brain", "com.jarvis.alpha.buddy", "com.jarvis.ollama"]`. Missing: executor, watchdog, temporal.server, temporal.ui, fluentbit, loki, power.brain, pg_backup (the last one is new from Session 1) | Quick win |
| AUDIT-9 | Rate-limit docstring/constant mismatch | P2 | ❌ OPEN | `brain/middleware/rate_limit_middleware.py:12` `MAX_REQUESTS = 300`; `:20` docstring says "100 req/min per user_id". One-line fix | Quick win |
| AUDIT-10 | V2 architecture doc stale (was 5 weeks at audit; now ~10) | P2 | ❌ OPEN | `docs/JARVIS_Alpha_Architecture_Review_V2.md:139` still references `RLSContextMiddleware`; doc predates Slab 4 SECDEF work + Session 1 backup pipeline + PR #149/#150/#151 skill work. V3 refresh needed | Session 4 candidate |
| AUDIT-11 | `thread_memory_extracts` documented but no migration creates it | P2 | ❌ OPEN | `docs/JARVIS_Alpha_Architecture_Review_V2.md:292` references the table; `brain/thread_manager.py:89` writes to it; `grep -l 'thread_memory_extracts' brain/db/migrations/*.sql` returns empty (91 migrations checked). Either dead doc/code reference or missing migration | Investigate (Session 4) |
| AUDIT-12 | Mypy + pytest-cov not in dev deps | P2 | ❌ OPEN | `pyproject.toml:24-28` — `dev = ["pytest>=7.4", "pytest-asyncio>=0.21", "ruff>=0.8"]` only. No mypy, no pytest-cov | Quick win |

**Score:** 1 CLOSED, 1 GUARD-LANDED, 1 PARTIAL, 9 OPEN. The two P0s are addressed (AUDIT-1 fully; AUDIT-2 still needs the multi-session coverage push). Both Session 1 and Session 1.5 hit their scoped targets.

---

## 2. New TDs Discovered (Session 1 + 1.5)

### 2a — Architecture debt (P1): Gateway egress consolidation

Session 1.5's broader sweep surfaced PUBLIC_INTERNET egress paths the original audit didn't catch (specifically the `subprocess curl` mechanism, which bypasses Python HTTP libraries):

| ID | Site | Host | Fix path |
|---|---|---|---|
| TD-S15-1 | `brain/routes/dev.py:116` | `api.github.com` | Gateway `/v1/cloud/github` proxy |
| TD-S15-2 | `brain/services/gmail_client.py:162,183,195` | `oauth2.googleapis.com` + `gmail.googleapis.com` (×2) | Gateway `/v1/cloud/google_oauth` + `/v1/cloud/gmail` |
| TD-S15-3 | `brain/routes/costs.py:458,462` | `api.anthropic.com` | Gateway `/v1/cloud/anthropic_admin` |
| TD-S15-4 | `brain/routes/costs.py:559` | `cloudbilling.googleapis.com` (via `subprocess.run(["curl", url])`) | Gateway `/v1/cloud/google_billing` |

Each TD has a `@pytest.mark.xfail(strict=True)` test in `tests/test_no_external_urls.py`. Fixing one flips xfail → xpass → test fails → forces removal from `KNOWN_VIOLATIONS`. Keeps the list honest.

### 2b — Operational / hygiene TDs

| ID | Description | Priority |
|---|---|---|
| TD-AUDIT-PERSIST | Audit outputs were written to `/tmp` and lost when `/tmp` aged out. Future audits must commit deliverables to `docs/audit/<date>/` as part of the same session that produces them — preferably as the very first PR of the session before any other work | P1 |
| TD-NOTIFY-LIB | `mm_notify` + `buddy_event` are duplicated in `scripts/pg_backup_alpha.sh` and `scripts/restore_drill_alpha.sh`. Extract to `scripts/lib/notify_helpers.sh` | P2 |
| TD-ADR0015-PROMOTE | ADR-0015 (Mattermost ChatOps) status is still `Proposed`. Code is shipping in production (PR #152 wires both scripts); promote to `Accepted` | P2 |
| TD-AGENT-LOGS | Under launchd, the backup script's `log_json` printf-without-fd routes to `pg_backup.agent.err.log` instead of `.out.log`. Functional work unaffected; investigate | P3 |
| TD-SIGPIPE-LABEL | When `gpg` is missing, `pg_dump | gpg` pipe breaks with pg_dump SIGPIPE rc=141; failure event reports stage=`pg_dump` instead of root cause (`gpg` missing). Cosmetic | P3 |
| TD-ORPHAN-SSH | `~/.ssh/unraid_backup` orphan key on Brain (timestamped March 12). Predates Session 1. Audit + likely `rm` | P3 |
| TD-BAK-CLEANUP | 8 `.bak*` files in repo (originally flagged by `ALPHA_STATE_TRUTH §17`). Current full list: `docs/SERVICE_IDENTITY_MODEL.md.bak_pre_td87`, `scripts/jarvisalpha_commit.sh.bak_pre_td88_step3`, `scripts/jarvisalpha_commit.sh.bak_pre_renderer`, `scripts/smoke_task_events_insert.sh.bak_pre_td57`, `scripts/jarvisalpha_pull.sh.bak_pre_td88`, `scripts/smoke_5d1_watchdog_agent.sh.bak_pre_td57`, `scripts/jarvisalpha_pull.sh.bak_pre_events`, `.vscode/settings.json.bak.20260419-104132`. `git rm` after confirming no live references | P3 |
| TD-SECRETS-2NODE | `BACKUP_GPG_PASSPHRASE` + `GATEWAY_TOKEN` now on Sandbox (`~/.secrets`) in addition to Brain (`~/jarvis/.secrets`). Deliberate DR-readiness trade-off (ADR-0013), but a future hardening pass should consider: (a) move DR decrypt to Endpoint; (b) Shamir-shard the passphrase with 2-of-3 reconstitution | P2 |
| TD-WAL-STREAM | Current RPO is 24h (nightly backup). Alpha-6 candidate: WAL streaming via `pg_receivewal` on Unraid for sub-24h RPO once workload warrants | P3 |
| TD-SECRETS-BAK-MAY7 | Pre-session `~/.secrets.bak.20260507-135749` on Sandbox left intact during Session 1 shred — predates this work, Ken decision required | P3 |
| TD-ENDPOINT-KEY-DOC | Sandbox→Endpoint deploy key created in TD-S1M1 closure. The canonical Endpoint deploy key likely lives on Air (no mesh-internal route had Endpoint access). Document where it lives, and whether the deploy-controller key should be reproducible from a documented seed | P2 |

### 2c — TDs from session 1 handoff that are NOW CLOSED

- ~~`httpx-in-Brain verification + static guard test`~~ → closed by PR #153.

---

## 3. Priority Ranking — what to do next

### 🔴 P0 — top risk now
- **AUDIT-2** (untested modules). Structural fragility behind every other change. Multi-session push.

### 🟡 P1 — observability cluster
- **AUDIT-3** (deep `/health` probe)
- **AUDIT-6** (activate Fluentbit → Loki shipper)
- **AUDIT-7** (rollback script — symmetric inverse of `jarvisalpha_deploy.sh`)
- **AUDIT-8** (extend `BRAIN_AGENTS` list)

### 🟡 P1 — architecture debt (Gateway egress consolidation)
- **TD-S15-1, -2, -3, -4** — close each xfail in turn by adding the Gateway proxy route + flipping the brain caller. One PR per TD keeps blast radius small.

### 🟢 Quick wins (≤1 session each)
- **AUDIT-9** — rate-limit docstring/constant sync (1-line fix)
- **AUDIT-12** — add `mypy` + `pytest-cov` to `[dependency-groups].dev`
- **TD-NOTIFY-LIB** — extract `mm_notify` + `buddy_event`
- **TD-ADR0015-PROMOTE** — flip status
- **TD-BAK-CLEANUP** — `git rm` 8 files

### 📚 Doc + cleanup (lower urgency, plan together)
- **AUDIT-10** — V2 → V3 architecture doc refresh
- **AUDIT-11** — `thread_memory_extracts` decision (dead reference vs missing migration)
- **AUDIT-5** — Alpha-5 Phase 5.0 plist templating (Brain/Endpoint/Sandbox)
- **TD-ENDPOINT-KEY-DOC** — Document canonical Endpoint deploy key location

---

## 4. Recommended Session Plan

### Session 2 — Observability Hardening
- AUDIT-3: deep `/health/ready` probe (DB pool + Ollama generate + Temporal client)
- AUDIT-6: activate Fluentbit → Loki shipper on Brain; smoke-test Grafana board
- AUDIT-7: write `scripts/jarvisalpha_rollback.sh` (symmetric inverse of deploy)
- AUDIT-8: extend `BRAIN_AGENTS` to all 8+ agents
- Quick wins folded in: AUDIT-9, AUDIT-12

### Session 3 — Gateway Egress Consolidation
- TD-S15-1: Gateway `/v1/cloud/github` proxy + flip `brain/routes/dev.py`
- TD-S15-2: Gateway `/v1/cloud/google_oauth` + `/v1/cloud/gmail` + flip `brain/services/gmail_client.py`
- TD-S15-3: Gateway `/v1/cloud/anthropic_admin` + flip `brain/routes/costs.py`
- TD-S15-4: Gateway `/v1/cloud/google_billing` + flip `brain/routes/costs.py` subprocess curl
- Each closure flips one strict-xfail to xpass, fails the test, forces removal from `KNOWN_VIOLATIONS`. PR-per-TD keeps reviews tight.

### Session 4 — V3 Doc Refresh + Cleanup
- AUDIT-10: V2 → V3 architecture doc refresh (router count 7 actual vs 12 documented; middleware list; known-issues; Slab 4 SECDEF; backup pipeline; httpx guard)
- AUDIT-11: `thread_memory_extracts` decision + migration if kept
- AUDIT-5: Brain/Endpoint/Sandbox plist `{{HOME}}` templating (Alpha-5 Phase 5.0)
- TD-BAK-CLEANUP, TD-ORPHAN-SSH, TD-ADR0015-PROMOTE, TD-NOTIFY-LIB, TD-ENDPOINT-KEY-DOC

### Parallel ongoing — Coverage push (AUDIT-2)
- One test PR per high-value untested module per week, prioritizing `brain/agents/*`, `brain/audit/secret_audit.py`, `brain/config/secrets.py`, `brain/core/db.py`, `brain/app.py`. Multi-session continuous work.

---

## 5. Cross-references

- **PR #152** — `feat(backup): encrypted pg backups + restore drill + scheduling` — merged 2026-05-28, squash sha `8a7824b`. Closes AUDIT-1.
- **PR #153** — `test(security): static guard — Brain no public egress` — merged 2026-05-28, squash sha `7037ab1`. Lands guard for AUDIT-4 + documents 5 strict-xfail TDs.
- **ADR-0013** — `docs/adr/ADR-0013-backup-recovery.md` — architecture record for the backup pipeline.
- **ADR-0015** — Mattermost ChatOps surface. Status: `Proposed` → flip to `Accepted` is TD-ADR0015-PROMOTE.
- **Session 1 handoff** — `docs/handoffs/HANDOFF_2026-05-27_session1_backup.md` — full operational runbook + DR procedure + §7 TD list (now superseded by §2 above).

---

## 6. Evidence Index

All references verified against current main `7037ab1` (2026-05-28):

| File | Cited At | Purpose |
|---|---|---|
| `scripts/pg_backup_alpha.sh` | exists | AUDIT-1 closure |
| `scripts/preflight_brain_backup.sh` | exists | AUDIT-1 closure |
| `scripts/restore_drill_alpha.sh` | exists | AUDIT-1 closure |
| `tests/test_no_external_urls.py` | exists, 319 lines | AUDIT-4 guard, 5 xfail-strict TDs |
| `brain/routes/health.py:127-129` | shallow health endpoint | AUDIT-3 evidence |
| `brain/routes/health.py:19-25` | `BRAIN_AGENTS` short list | AUDIT-8 evidence |
| `brain/middleware/rate_limit_middleware.py:12,20` | 300 vs "100 req/min" | AUDIT-9 evidence |
| `common/jarvis_common/logging_config.py:100-102` | stdout-only handler | AUDIT-6 evidence |
| `brain/routes/dev.py:116` | `api.github.com` literal | TD-S15-1 |
| `brain/services/gmail_client.py:162,183,195` | Google OAuth + Gmail literals | TD-S15-2 |
| `brain/routes/costs.py:458,462,559` | Anthropic admin + Cloud Billing | TD-S15-3, -4 |
| `pyproject.toml:24-28` | dev deps list | AUDIT-12 evidence |
| `docs/JARVIS_Alpha_Architecture_Review_V2.md:139,292` | `RLSContextMiddleware`, `thread_memory_extracts` | AUDIT-10, AUDIT-11 |
| `brain/thread_manager.py:89` | code writes to `thread_memory_extracts` | AUDIT-11 |
| `launchagents/*.template.plist` | 7 templates | AUDIT-5 (current state) |
| `launchagents/*.plist` (non-template) | 15 hardcoded | AUDIT-5 (remaining work) |
| `brain/db/migrations/*.sql` | 91 files | AUDIT-11 (no `thread_memory_extracts` migration found) |
