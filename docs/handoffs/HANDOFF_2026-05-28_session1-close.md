# HANDOFF — 2026-05-28 Session 1 + 1.5 close-out

**Filename:** `HANDOFF_2026-05-28_session1-close.md`
**Canonical location:** `~/jarvis-alpha/docs/handoffs/HANDOFF_2026-05-28_session1-close.md`
**Predecessors:** `HANDOFF_2026-05-27_session1_backup.md` (Phase 8 backup pipeline) + Session 1.5 httpx-guard PR thread
**Closes:** P0 from Phase 0 audit (no working backups, no proven recovery) + lands the V2 §1 invariant guard

---

## Status: Session 1 + 1.5 SHIPPED

All 4 nodes (Brain, Sandbox, Gateway, Endpoint) are on main `7037ab1`. Encrypted Postgres backups run nightly on Brain at 02:30 local; weekly restore drill runs on Sandbox Sundays at 03:30 local. Both schedules verified end-to-end including launchd kickstart proof (Phase 8A) and `--inject-corrupt` FAIL-path proof. The V2 §1 "Brain never touches public internet directly" invariant is now enforced as a CI test (`tests/test_no_external_urls.py`). Five real PUBLIC_INTERNET egress paths surfaced during that work are documented as strict-xfail TDs that fail-loud the moment they're "fixed" without removing the entry. The P0 backup risk from the Phase 0 audit is closed.

---

## What shipped

### PR #152 — Backup pipeline (merged `8a7824b`)
**Title:** `feat(backup): encrypted pg backups + restore drill + scheduling` · **+1,875 lines · 9 files**

| File | Purpose |
|---|---|
| `scripts/preflight_brain_backup.sh` | SSH preflight (host, key perms, target writable, free GB, passphrase set, pg_dump) → JSON gate |
| `scripts/pg_backup_alpha.sh` | `pg_dump → gpg fd 3 → scp .partial → sha256 verify → atomic rename → manifest → retention`; `mm_notify` + `buddy_event` inline |
| `scripts/restore_drill_alpha.sh` | Sandbox DR drill: pull → decrypt → ephemeral pgvector container → restore → verify; `--keep`, `--inject-corrupt` flags |
| `launchagents/com.jarvis.alpha.pg_backup.template.plist` | Nightly 02:30 schedule, `{{HOME}}` placeholder |
| `launchagents/com.jarvis.alpha.restore_drill.template.plist` | Weekly Sunday 03:30 schedule |
| `scripts/install_launchagents.py` | +2 entries in `SERVICE_NODE_MAP` (`pg_backup→brain`, `restore_drill→sandbox`) |
| `tests/test_backup_scripts.py` | 32 static + retention-algorithm guards |
| `docs/adr/ADR-0013-backup-recovery.md` | Architecture record (draft for jarvis-standards promotion) |
| `docs/handoffs/HANDOFF_2026-05-27_session1_backup.md` | Full operational record + DR runbook |

### PR #153 — httpx static guard (merged `7037ab1`)
**Title:** `test(security): static guard — Brain no public egress` · **+319 lines · 1 file**

| File | Purpose |
|---|---|
| `tests/test_no_external_urls.py` | AST sweep of every `brain/*.py` for literal URLs; allowlist (`127.0.0.1`, `localhost`, `*.tail40ed36.ts.net`, `jarvis-*`); strict xfail on each of 5 documented violations |

---

## Current system state

### All 4 nodes on `7037ab1`
| Node | Branch | HEAD |
|---|---|---|
| Sandbox (controller) | `main` | `7037ab1` |
| Brain | `main` | `7037ab1` |
| Gateway | `main` | `7037ab1` |
| Endpoint | `main` | `7037ab1` |

### Schedule
| Agent | Node | Cron | Next fire |
|---|---|---|---|
| `com.jarvis.alpha.pg_backup` | Brain (`jarvisbrain`) | nightly 02:30 local | next 02:30 EDT |
| `com.jarvis.alpha.restore_drill` | Sandbox (`jarvissand`) | weekly Sunday 03:30 local | next Sunday 03:30 EDT |

Both `RunAtLoad = false`. Manual kickstart of pg_backup proven end-to-end Phase 8A.

### Mattermost surface (per ADR-0015)
| Channel | Used by | Severity |
|---|---|---|
| `#alpha-events` | pg_backup + restore_drill | `info` on success/dry-run, `critical` also routes here |
| `#alerts` | gateway auto-route on severity=`critical` | preflight failed, per-DB failure, drill FAILED |
| `#needs-input` | (reserved) approval requests | not yet wired by Session 1 |

### Secrets map (intact)
| Secret | Brain | Sandbox | Out-of-band |
|---|---|---|---|
| `BACKUP_GPG_PASSPHRASE` | `~/jarvis/.secrets` (600) | `~/.secrets` (600) | 1Password (Ken-verified Phase 2) |
| `BACKUP_SSH_KEY` (Brain→Unraid) | `~/.ssh/jarvis_alpha_backup` (600) | — | — |
| `RESTORE_SSH_KEY` (Sandbox→Unraid) | — | `~/.ssh/jarvis_alpha_restore` (600) | — |
| `GATEWAY_TOKEN` | `~/jarvis/.secrets` | `~/.secrets` (DR readiness) | — |
| Sandbox→Endpoint deploy key (TD-S1M1) | — | `~/.ssh/jarvis_endpoint_deploy` (600) + `~/.ssh/config` Host block | — |

Transient `.secrets.bak.*` files from Phase 5/6 secret moves were shredded with `rm -P` (Phase 8B). One pre-session backup `~/.secrets.bak.20260507-135749` remains on Sandbox (predates session, Ken decision — TD-SECRETS-BAK-MAY7).

---

## Open gaps

Canonical source: **`docs/audit/GAP_ANALYSIS_v2.md`**. Summary of top 3 risks now:

1. **AUDIT-2** — ~80% of brain modules untested. Structural fragility behind every change. Multi-session push.
2. **AUDIT-3 / AUDIT-6 / AUDIT-7** — observability blind spots: `/health` is shallow, Loki/Fluentbit shippers inactive, no rollback script. Bundled as Session 2 target.
3. **TD-S15-1..4** — 5 PUBLIC_INTERNET egress paths in Brain (1 from original audit, 4 surfaced by Session 1.5 sweep). Each is a strict-xfail TD that fails-loud on fix-without-cleanup. Bundled as Session 3 target.

---

## Active TDs (sorted by priority)

### P1 — architecture debt
- **TD-S15-1** — `brain/routes/dev.py:116` → `api.github.com`. Gateway `/v1/cloud/github`.
- **TD-S15-2** — `brain/services/gmail_client.py:162,183,195` → Google OAuth + Gmail API. Gateway `/v1/cloud/google_oauth` + `/v1/cloud/gmail`.
- **TD-S15-3** — `brain/routes/costs.py:458,462` → `api.anthropic.com`. Gateway `/v1/cloud/anthropic_admin`.
- **TD-S15-4** — `brain/routes/costs.py:559` → `cloudbilling.googleapis.com` via `subprocess curl`. Gateway `/v1/cloud/google_billing`.
- **TD-AUDIT-PERSIST** — Audit deliverables must commit to `docs/audit/<date>/` in the same session that produces them (this doc is the corrective action; future audits must follow suit).

### P2 — operational hygiene
- **TD-NOTIFY-LIB** — extract `mm_notify` + `buddy_event` to shared lib
- **TD-ADR0015-PROMOTE** — flip ADR-0015 from `Proposed` → `Accepted` (code shipped)
- **TD-SECRETS-2NODE** — passphrase + gateway token on 2 nodes; future hardening via Endpoint relocation or SSS shard
- **TD-ENDPOINT-KEY-DOC** — document canonical Endpoint deploy key location (likely Air); reproducibility audit

### P3 — quality of life
- **TD-AGENT-LOGS** — launchd routing of `pg_backup` stdout to `.err.log` instead of `.out.log`
- **TD-SIGPIPE-LABEL** — `dump_failed` event stage mislabel when `gpg` is missing
- **TD-ORPHAN-SSH** — `~/.ssh/unraid_backup` orphan key (March 12) on Brain
- **TD-BAK-CLEANUP** — `git rm` 8 `.bak*` files (full list in GAP_ANALYSIS_v2 §2b)
- **TD-WAL-STREAM** — Alpha-6 candidate for sub-24h RPO
- **TD-SECRETS-BAK-MAY7** — `~/.secrets.bak.20260507-135749` on Sandbox (predates session)

---

## Recommended next: Session 2 — Observability Hardening

### Goals
1. Replace shallow `/health` with deep `/health/ready` that probes DB pool + Ollama generate + Temporal client. Cite reuse of `collect_temporal_storage_snapshot` pattern (already in repo).
2. Activate Fluentbit → Loki shipper on Brain. Plists are already installed; the shipper code path in `common/jarvis_common/logging_config.py:100-102` only attaches a stdout handler.
3. Write `scripts/jarvisalpha_rollback.sh` as the symmetric inverse of `scripts/jarvisalpha_deploy.sh`. Should accept a target commit, refuse to rollback to a non-parent, per-node `git checkout <sha>` + `jarvisalpha_pull.sh` + service restart classifier.
4. Extend `BRAIN_AGENTS` (`brain/routes/health.py:19-25`) to all 8+ agents currently installed on Brain.
5. Fold in quick wins: **AUDIT-9** (rate-limit constant/docstring sync — one-line fix at `brain/middleware/rate_limit_middleware.py:12,20`), **AUDIT-12** (add `mypy` + `pytest-cov` to `[dependency-groups].dev` in `pyproject.toml:24-28`).

### In-scope
- `brain/routes/health.py` (deep probe + extended agents)
- `common/jarvis_common/logging_config.py` (Fluentbit handler)
- `scripts/jarvisalpha_rollback.sh` (new)
- `brain/middleware/rate_limit_middleware.py` (sync)
- `pyproject.toml` (dev deps)

### Out-of-scope (defer to later sessions)
- Gateway egress consolidation (Session 3)
- V3 doc refresh (Session 4)
- Alpha-5 Phase 5.0 plist templating (Session 4)
- AUDIT-2 coverage push (parallel ongoing)

### Est duration
1 focused session, ~6–8 hours with paired CC. Smaller blast radius per file than Session 1 (no system-level scheduling, no secrets pre-positioning).

---

## §8 — Resume / discovery commands for next session

```
# Confirm the four nodes are still on main
cd ~/jarvis-alpha && git rev-parse --short HEAD
ssh jarvisbrain@jarvis-brain 'cd ~/jarvis-alpha && git rev-parse --short HEAD'
ssh gate@jarvis-gateway.tail40ed36.ts.net 'cd ~/jarvis-alpha && git rev-parse --short HEAD'
ssh jarvisendpoint@jarvis-endpoint.tail40ed36.ts.net 'cd ~/jarvis-alpha && git rev-parse --short HEAD'

# Confirm both LaunchAgents still loaded
launchctl list | grep com.jarvis.alpha.restore_drill
ssh jarvisbrain@jarvis-brain 'launchctl list | grep com.jarvis.alpha.pg_backup'

# Last backup manifest on Unraid
ssh -i ~/.ssh/jarvis_alpha_restore root@192.168.30.10 \
  'ls -lt /mnt/user/Backups/jarvis-alpha/manifests/ | head -5'

# Last drill report on Sandbox
ls -t ~/jarvis/logs/restore_drill_*.json 2>/dev/null | head -1 | xargs cat | python3 -m json.tool

# Last backup event stream on Brain
ssh jarvisbrain@jarvis-brain 'tail -20 ~/jarvis/logs/pg_backup.log | jq -c "select(.event==\"run_complete\")"'

# Mattermost reachability (via Gateway from Sandbox)
curl -sk -m 5 https://jarvis-gateway.tail40ed36.ts.net:8283/health | head -200

# Re-run the backup test suite
cd ~/jarvis-alpha && .venv/bin/pytest tests/test_backup_scripts.py tests/test_no_external_urls.py -v

# Buddy event feed from Brain
ssh jarvisbrain@jarvis-brain \
  "/opt/homebrew/Cellar/postgresql@16/16.13/bin/psql -d jarvis_alpha -tAc \"
    SELECT created_at, event_type, priority, title, source
    FROM alpha_buddy_events
    WHERE source IN ('pg_backup_alpha','restore_drill_alpha')
    ORDER BY created_at DESC LIMIT 20
  \""
```

---

## Resume command (paste into fresh Claude/CC)

```
Read docs/handoffs/HANDOFF_2026-05-28_session1-close.md
and docs/audit/GAP_ANALYSIS_v2.md.
Start Session 2 architecture review.
```
