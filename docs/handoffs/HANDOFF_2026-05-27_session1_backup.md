# HANDOFF — 2026-05-27/28 Session 1: Encrypted PG Backups + Restore Drill

**Filename:** `HANDOFF_2026-05-27_session1_backup.md`
**Canonical location:** `~/jarvis-alpha/docs/handoffs/HANDOFF_2026-05-27_session1_backup.md`
**Spans:** jarvis-alpha (Brain backup, Sandbox restore drill, Unraid storage, Mattermost notify)
**Predecessor:** Phase 0 audit `/tmp/alpha_audit_2026-05-27/*.md`
**Mode:** Paired with Ken across Sandbox CLI → SSH to Brain
**Closes:** P0 from audit (no working backups, no proven recovery)

---

## §1 — What shipped (one paragraph)

A full encrypted Postgres backup pipeline (`pg_dump → gpg AES256 → scp →
sha256-verified atomic rename → manifest → 30-day-and-first-of-month retention`)
runs nightly on Brain at 02:30 local. A weekly restore drill at Sunday 03:30
local on Sandbox pulls the latest dump from Unraid, decrypts, restores into an
ephemeral pgvector container, verifies structure + row counts against live Brain
reference, and tears the container down — proving recoverability rather than
assuming it. Both paths emit Mattermost notifications (success → `#alpha-events`
info, failure → `#alerts` critical via gateway severity auto-routing) and write
buddy_event rows for in-database observability. Verified end-to-end: real
backup (3 DBs, ~11 MB, 5s), success drill, fail drill via `--inject-corrupt`,
launchctl kickstart fire of the scheduled path.

---

## §2 — Artifacts

| Path | Purpose |
|---|---|
| `scripts/preflight_brain_backup.sh` | SSH-based preflight (host, key perms, ssh reach, target writable, free GB, passphrase set, pg_dump available) → JSON gate |
| `scripts/pg_backup_alpha.sh` | Main backup: pg_dump → gpg fd 3 → scp .partial → sha256 verify → atomic rename → manifest → retention; `mm_notify` + `buddy_event` inline |
| `scripts/restore_drill_alpha.sh` | DR drill on Sandbox: pull → decrypt → ephemeral container → restore → verify (table count + 4 row probes) → notify; `--keep` and `--inject-corrupt` flags |
| `launchagents/com.jarvis.alpha.pg_backup.template.plist` | Nightly 02:30 schedule, `{{HOME}}` placeholder |
| `launchagents/com.jarvis.alpha.restore_drill.template.plist` | Weekly Sunday 03:30 schedule |
| `scripts/install_launchagents.py` | +2 entries in `SERVICE_NODE_MAP` (`pg_backup→brain`, `restore_drill→sandbox`) |
| `tests/test_backup_scripts.py` | 32 static + retention-algorithm guards |
| `docs/adr/ADR-0013-backup-recovery.md` | Architecture record (draft for jarvis-standards promotion) |

---

## §3 — Operations runbook

### Run a manual backup (Brain)
```
ssh jarvisbrain@jarvis-brain 'bash ~/jarvis-alpha/scripts/pg_backup_alpha.sh'
# dry-run (schema-only, no scp):
ssh jarvisbrain@jarvis-brain 'bash ~/jarvis-alpha/scripts/pg_backup_alpha.sh --dry-run'
# single DB:
ssh jarvisbrain@jarvis-brain 'bash ~/jarvis-alpha/scripts/pg_backup_alpha.sh --db jarvis_alpha'
```

### Run a manual restore drill (Sandbox)
```
bash ~/jarvis-alpha/scripts/restore_drill_alpha.sh
# preserve container + temp files for inspection:
bash ~/jarvis-alpha/scripts/restore_drill_alpha.sh --keep
# inject corruption to verify the FAIL path catches bad backups:
bash ~/jarvis-alpha/scripts/restore_drill_alpha.sh --inject-corrupt
```

### Inspect the schedule
```
# Brain
ssh jarvisbrain@jarvis-brain 'launchctl list | grep com.jarvis.alpha.pg_backup'
ssh jarvisbrain@jarvis-brain 'launchctl print gui/$(id -u)/com.jarvis.alpha.pg_backup | head -30'
# Sandbox
launchctl list | grep com.jarvis.alpha.restore_drill
launchctl print gui/$(id -u)/com.jarvis.alpha.restore_drill | head -30
```

### Real disaster recovery (Brain unreachable)

This is the procedure the drill rehearses every Sunday. To recover Alpha onto a
fresh Postgres on Sandbox:

```
# 1. Confirm secrets on Sandbox
grep -c '^BACKUP_GPG_PASSPHRASE=' ~/.secrets    # must be 1
grep -c '^RESTORE_SSH_KEY=' ~/.secrets          # must be 1

# 2. Pull the desired dump (latest or a specific date) from Unraid
ssh -i ~/.ssh/jarvis_alpha_restore root@192.168.30.10 \
  "ls -t /mnt/user/Backups/jarvis-alpha/dumps/jarvis_alpha_*.dump.gpg | head -10"
scp -i ~/.ssh/jarvis_alpha_restore \
  root@192.168.30.10:/mnt/user/Backups/jarvis-alpha/dumps/jarvis_alpha_<TS>.dump.gpg \
  ~/jarvis/tmp/recovery.dump.gpg
chmod 600 ~/jarvis/tmp/recovery.dump.gpg

# 3. Decrypt
gpg --decrypt --batch --quiet --passphrase-fd 3 \
  --output ~/jarvis/tmp/recovery.dump ~/jarvis/tmp/recovery.dump.gpg \
  3< <(awk -F= '/^BACKUP_GPG_PASSPHRASE=/{sub(/^[^=]+=/,""); print; exit}' ~/.secrets)

# 4. Restore into a fresh DB (local or container)
createdb jarvis_alpha_restored
psql -d jarvis_alpha_restored -c "CREATE EXTENSION IF NOT EXISTS vector;"
psql -d jarvis_alpha_restored -c "CREATE EXTENSION IF NOT EXISTS pgcrypto;"
pg_restore --no-owner --no-privileges --no-acl \
  -d jarvis_alpha_restored ~/jarvis/tmp/recovery.dump

# 5. Verify (compare to most recent manifest)
psql -d jarvis_alpha_restored -c "
  SELECT count(*) FROM information_schema.tables WHERE table_schema='public';
"
# 6. Shred temp files
rm -P ~/jarvis/tmp/recovery.dump ~/jarvis/tmp/recovery.dump.gpg
```

`pg_restore` will report 1–2 errors per `CREATE EXTENSION pgaudit` line if the
restore target lacks pgaudit — this is expected and matches the drill's
acceptance logic.

---

## §4 — Schedule

| Agent | Node | Schedule | Next fire after this handoff |
|---|---|---|---|
| `com.jarvis.alpha.pg_backup` | Brain | nightly 02:30 local | 2026-05-29 02:30 EDT |
| `com.jarvis.alpha.restore_drill` | Sandbox | weekly Sunday 03:30 local | 2026-05-31 03:30 EDT |

Both `RunAtLoad = false`. Manual kickstart proven end-to-end in Phase 8A (run_id
`2026-05-28_151235`, HTTP 200 to Mattermost, all 3 DBs landed on Unraid).

---

## §5 — Secrets map

| Secret | Brain | Sandbox | Out-of-band |
|---|---|---|---|
| `BACKUP_GPG_PASSPHRASE` | `~/jarvis/.secrets` (600) | `~/.secrets` (600) | 1Password (Ken-verified Phase 2) |
| `BACKUP_SSH_KEY` (Brain → Unraid) | `~/.ssh/jarvis_alpha_backup` (600) | — | — |
| `RESTORE_SSH_KEY` (Sandbox → Unraid) | — | `~/.ssh/jarvis_alpha_restore` (600) | — |
| `GATEWAY_TOKEN` (Mattermost notify) | `~/jarvis/.secrets` | `~/.secrets` | — |
| `RESTORE_SSH_{HOST,USER,KEY,SOURCE_DIR}` | — | `~/.secrets` | — |

Unraid `/boot/config/ssh/root/authorized_keys` holds both pubkeys (Brain backup
key + Sandbox restore key). Persists across reboots per Unraid 7.2.3 path.

Transient `.secrets.bak.*` files created during Phase 5/6 secret moves were
shredded with `rm -P` in Phase 8B.

---

## §6 — Mattermost surface

| Severity | Channel(s) | Event |
|---|---|---|
| `info` | `#alpha-events` | Backup OK, drill PASSED, dry-run OK |
| `critical` | `#alpha-events` + `#alerts` (gateway severity auto-routing) | Preflight failed, per-DB failure, drill FAILED |

Buddy events: same data, written to `alpha_buddy_events` table on Brain.
`event_type=system` priority 1 for success; `event_type=alert` priority 3 for
failure. Sandbox writes via best-effort `ssh jarvisbrain` — failures of that ssh
are logged but never block the drill.

---

## §7 — Tech debt surfaced this session

- **TD: SIGPIPE stage mislabel on gpg-missing failure.** When `gpg` is removed
  from PATH, `pg_dump | gpg` pipe breaks with pg_dump SIGPIPE rc=141; the
  failure event reports stage=pg_dump rather than the root cause. Cosmetic; fix
  by inspecting PIPESTATUS for which side died first.
- **TD: `mm_notify` + `buddy_event` duplicated** in `pg_backup_alpha.sh` and
  `restore_drill_alpha.sh`. Extract to `scripts/lib/notify_helpers.sh` (or
  Python module if more callers materialize).
- **TD: ADR-0015 status `Proposed` → `Accepted`.** Code is now shipping
  Mattermost notifications in production; the ADR can advance.
- **TD: `~/.ssh/unraid_backup` orphan key (March 12)** on Brain. Predates this
  session; audit and likely `rm` after confirming it's not referenced anywhere.
- **TD: 8 `.bak*` files in repo** (surfaced in Phase 0 audit). `git rm` after
  confirming no live references.
- **TD: `GATEWAY_TOKEN` + `BACKUP_GPG_PASSPHRASE` on Sandbox** — future
  hardening: move DR decrypt path to Endpoint instead of Sandbox, or
  Shamir-shard the passphrase and require 2-of-3 nodes to reconstitute.
- **TD: httpx-in-Brain verification + static guard test** (originally Session
  1.5; deferred to keep this session focused on the P0).
- **TD: WAL streaming for sub-24h RPO** — Alpha-6 candidate per ADR-0013
  reversal condition #3.
- **TD: agent stdout went to `pg_backup.agent.err.log` instead of `.out.log`**
  under launchd. The script's `log_json` printf-without-fd should go to
  stdout; under launchd something routes to fd 2. Probably an `exec` redirect
  or set -e quirk. Functional work unaffected; investigate later.
- **TD: cleanup of `~/.secrets.bak.20260507-135749`** on Sandbox — predates
  this session, left intact per scope discipline; Ken decision.
- **TD: pre-existing legacy plists in `launchagents/*.plist`** (no `.template`
  suffix; from old machines). Phase 7 audit confirms they're gitignored
  correctly via the existing `launchagents/*.plist` + `!launchagents/*.template.plist`
  rules; the template-pattern conversion of those legacy ones is future work.

---

## §8 — Resume / discovery commands for next session

```
# Check the latest backup landed
ssh jarvisbrain@jarvis-brain 'ls -lt /Users/jarvisbrain/jarvis/logs/manifests/ | head -5'
ssh jarvisbrain@jarvis-brain 'tail -20 ~/jarvis/logs/pg_backup.log | jq -c "select(.event==\"run_complete\")"'

# Check Unraid storage
ssh -i ~/.ssh/jarvis_alpha_restore root@192.168.30.10 \
  'ls -lt /mnt/user/Backups/jarvis-alpha/dumps/ | head -10; \
   df -h /mnt/user/Backups | tail -1'

# Check the drill's most recent JSON report
ls -t ~/jarvis/logs/restore_drill_*.json | head -1 | xargs cat | python3 -m json.tool

# Check buddy_event feed
ssh jarvisbrain@jarvis-brain \
  "/opt/homebrew/Cellar/postgresql@16/16.13/bin/psql -d jarvis_alpha -tAc \"
    SELECT created_at, event_type, priority, title, source
    FROM alpha_buddy_events
    WHERE source IN ('pg_backup_alpha','restore_drill_alpha')
    ORDER BY created_at DESC LIMIT 20
  \""

# Verify both LaunchAgents still loaded
ssh jarvisbrain@jarvis-brain 'launchctl list | grep com.jarvis.alpha.pg_backup'
launchctl list | grep com.jarvis.alpha.restore_drill

# Run the test suite
cd ~/jarvis-alpha && .venv/bin/pytest tests/test_backup_scripts.py -v
```

---

## §9 — Acceptance proofs from this session

| Phase | Proof |
|---|---|
| 0 | Audit deliverables in `/tmp/alpha_audit_2026-05-27/` (5 files) |
| 1 | SSH passwordless Brain → Unraid; persistent key in `/boot/config/ssh/root/authorized_keys` |
| 2 | `BACKUP_GPG_PASSPHRASE` set on Brain; verified in 1Password (Ken-confirmed) |
| 3 | Real backup completed (3 DBs ~11 MB ~5s); sha256 round-trip verified |
| 4 | Mattermost dry-run + real success + failure path all HTTP 200 (Ken-confirmed both channels) |
| 5 | Sandbox SSH key + secrets positioned; pull test bytes match manifest |
| 6 | Drill PASS (table_count 68/68 + 4 row probes match) and FAIL (`--inject-corrupt`) both verified end-to-end with Mattermost + buddy event rows (Ken-confirmed both channels) |
| 7 | Both LaunchAgents installed + bootstrapped on respective nodes; `state=not running`, `runs=0` (RunAtLoad=false honored) |
| 8A | launchctl kickstart fired backup under scheduled context → HTTP 200, 3 DBs on Unraid (Ken-confirmed) |
| 8C | 32/32 pytest assertions passing |
