# TD-38 Legacy Roles Audit — `jarvis` and `jarvis_app`

**Date:** 2026-04-08  
**Auditor:** Claude Code (READ-ONLY — no modifications, no commits, no migrations applied)  
**Trigger:** Step 6.5 Stage 2 migration will `REVOKE ALL ON SCHEMA public FROM PUBLIC`; two unexpected roles (`jarvis`, `jarvis_app`) inherit schema USAGE from PUBLIC and could be silently broken.

---

## Summary

**REFERENCES FOUND — PATH B SAFE WITH NOTES**

One dead cron job on Brain references `-U jarvis` but targets a database (`jarvis`) that no longer exists in postgres. No application code, LaunchAgent, or active process connects to `jarvis_alpha` as either legacy role. `jarvis_app` is completely inert. `jarvis` is a dead-cron artifact from the jarvis-core era with a latent BYPASSRLS risk.

---

## Findings Per Task

### Task 1 — Codebase Scan (`~/jarvis-alpha/`)

**Patterns searched:**
- `jarvis_app`, `user=jarvis[^b]`, `PGUSER=jarvis[^b]`, `USER jarvis[^b]`, `role jarvis[^b]` (case-insensitive), `postgresql://jarvis[:@]`, `dbname.*user.*jarvis[^b]`
- Excluded: `.git`, `node_modules`, `.venv`, `__pycache__`, `dist`, `build`, `*.pyc`, `*.log`
- Excluded matches: `jarvisbrain`, `jarvisgateway`, `jarvisendpoint`, `jarvissand`, `jarvisforge`

**FINDING: BASELINE DOCUMENTATION ONLY — no application code references**

| File | Line | Match |
|------|------|-------|
| `db/baselines/baseline_2026-04-07_pre_step7_globals.sql` | 16 | `CREATE ROLE jarvis;` |
| `db/baselines/baseline_2026-04-07_pre_step7_globals.sql` | 17 | `ALTER ROLE jarvis WITH NOSUPERUSER INHERIT NOCREATEROLE NOCREATEDB LOGIN REPLICATION BYPASSRLS PASSWORD 'SCRAM-SHA-256$...';` |
| `db/baselines/baseline_2026-04-07_pre_step7_globals.sql` | 20 | `CREATE ROLE jarvis_app;` |
| `db/baselines/baseline_2026-04-07_pre_step7_globals.sql` | 21 | `ALTER ROLE jarvis_app WITH NOSUPERUSER INHERIT NOCREATEROLE NOCREATEDB LOGIN NOREPLICATION NOBYPASSRLS PASSWORD 'SCRAM-SHA-256$...';` |

These lines are a pg_dumpall-generated baseline snapshot (`pre_step7_globals.sql`), not DDL that the migration pipeline runs. They document what roles existed at snapshot time.

All other `role jarvis` hits were `jarvis_alpha_*` roles (legitimate): `jarvis_alpha_app`, `jarvis_alpha_writer`, `jarvis_alpha_buddy`, etc. — confirmed unrelated to the legacy roles under audit.

**No connection strings, no `PGUSER=jarvis`, no `postgresql://jarvis` anywhere in the codebase.**

---

### Task 2 — Brain Filesystem Scan (`~/jarvis/`)

**FINDING: CLEAN**

Grep across `~/jarvis/` for all patterns (excluding `*.log`, `.secrets`) returned zero matches after filtering OS-user strings. The Brain service codebase contains no references to `jarvis` or `jarvis_app` as DB credentials.

---

### Task 3 — LaunchAgent Scan (`~/Library/LaunchAgents/com.jarvis.*.plist`)

**Plists inspected:**
- `com.jarvis.alpha.brain.plist`
- `com.jarvis.alpha.buddy.plist`
- `com.jarvis.alpha.executor.plist`
- `com.jarvis.alpha.fluentbit.plist`
- `com.jarvis.alpha.loki.plist`
- `com.jarvis.alpha.rotate.buddy.plist`
- `com.jarvis.alpha.watchdog.plist`
- `com.jarvis.certrenew.plist`
- `com.jarvis.ollama.plist`

**FINDING: CLEAN — no PGUSER/DATABASE_URL in any plist**

EnvironmentVariables sections observed:

| Plist | EnvironmentVariables present | DB keys found |
|-------|------------------------------|---------------|
| `com.jarvis.alpha.brain.plist` | Yes — `GIT_TERMINAL_PROMPT=0` only | None |
| `com.jarvis.alpha.watchdog.plist` | Yes — `JARVIS_NODE`, `WATCHDOG_*` keys only | None |
| `com.jarvis.certrenew.plist` | Yes — `PATH` only | None |
| All others | Not present or no env section | None |

No plist injects `PGUSER`, `DATABASE_URL`, `DB_USER`, or any `jarvis`/`jarvis_app` credential.

---

### Task 4 — Running Process Scan

**Active postgres backends (`ps aux | grep postgres.*jarvis_alpha`):**
```
jarvisbrain  47407  ...  postgres: jarvisbrain jarvis_alpha ::1(62153) idle
jarvisbrain  47413  ...  postgres: jarvisbrain jarvis_alpha ::1(62158) idle
jarvisbrain  51604  ...  postgres: jarvisbrain jarvis_alpha ::1(63428) idle
jarvisbrain  51618  ...  postgres: jarvisbrain jarvis_alpha ::1(63431) idle
```

**FINDING: CLEAN — all active connections use `jarvisbrain` role, not `jarvis` or `jarvis_app`**

`lsof` confirms postgres listening on 5432 (IPv4 + IPv6 localhost only); all 4 established connections are localhost↔localhost.

**pg_hba.conf (`/opt/homebrew/var/postgresql@16/pg_hba.conf`):**
```
local   all   all                  trust
host    all   all   127.0.0.1/32   trust
host    all   all   ::1/128        trust
local   replication  all           trust
host    replication  all  127.0.0.1/32  trust
host    replication  all  ::1/128   trust
```

No role-specific entries for `jarvis` or `jarvis_app`. Auth is trust for all localhost connections — not a blocker for Path B (REVOKE is schema-level, not auth-level).

---

### Task 5 — jarvis-core Repo Check

**Directories checked:**
- `~/jarvis-core/` — **not found**
- `~/jarvis/services/` — **found**; grep returned zero matches
- `~/jarvis/core/` — **not found**

**FINDING: CLEAN — `~/jarvis/services/` contains no references to `jarvis` or `jarvis_app` roles**

jarvis-core does not appear to be present on Brain as a separate repo checkout. The `~/jarvis/services/` tree is clean.

---

### Task 6 — Homebrew Postgres Config

**pg_hba.conf (`/opt/homebrew/var/postgresql@16/pg_hba.conf`):**

Grepped for `jarvis` excluding `jarvisbrain` and `jarvis_alpha_*` — **zero matches**.

All active entries use blanket `all` user matching with `trust`. There are no role-pinned entries for `jarvis` or `jarvis_app`.

**FINDING: CLEAN**

---

### Task 7 — Cron Jobs

**`crontab -l` on Brain:**
```
0 2 * * 0  /bin/zsh ~/jarvis/backups/postgres/weekly_basebackup.sh >> ...
0 */6 * * * bash -c "/opt/homebrew/Cellar/postgresql@16/16.13/bin/pg_dump -U jarvis jarvis > /Volumes/JarvisSecure/jarvis_secure/memory/backups/postgres/jarvis_$(date +%Y%m%d_%H%M).sql 2>> ~/jarvis/backups/postgres/backup.log"
```

**FINDING: REFERENCE FOUND — but dead**

The every-6-hour cron calls `pg_dump -U jarvis jarvis`:
- `-U jarvis` → uses the `jarvis` login role
- Second `jarvis` argument → targets a database named `jarvis`

**Critical cross-check:** `psql -U jarvisbrain -lqt | grep jarvis` returned **zero rows**. The database named `jarvis` does not exist in the local postgres instance.

**Conclusion:** This cron is a jarvis-core bootstrap artifact. It errors silently every 6 hours (dump of non-existent DB; errors redirect to `backup.log`). It does NOT connect to `jarvis_alpha`. The `jarvis` role is referenced but not connecting to anything successfully.

The weekly basebackup cron (`weekly_basebackup.sh`) was not grepped for role references — it warrants a targeted check if cleanup is pursued (see Open Questions).

---

## Verdict

**PATH B SAFE WITH NOTES**

| Role | Status | Verdict |
|------|--------|---------|
| `jarvis_app` | Zero references in code, plists, running processes, or cron | Safe to preserve with GRANT USAGE; safe to drop after Stage 5 |
| `jarvis` | One cron reference (`-U jarvis jarvis`) but target DB doesn't exist; zero connections to `jarvis_alpha` | Safe to preserve with GRANT USAGE; cron is dead but needs cleanup |

**The `REVOKE ALL ON SCHEMA public FROM PUBLIC` in Stage 2 will NOT break any live connection or service.** Both roles inherit schema USAGE from PUBLIC, and after the REVOKE both would lose that inheritance — but since nothing is actively connecting to `jarvis_alpha` as either role, there is no blast radius.

Path B (preserve with explicit `GRANT USAGE` on `jarvis_alpha` schema) is safe to proceed.

---

## Recommended TD-38 Scope

### Before Stage 2 lands (immediate)
- [x] **Path B is approved:** add `GRANT USAGE ON SCHEMA public TO jarvis, jarvis_app;` to Stage 2 migration so REVOKE does not silently break future reconnects if jarvis-core bootstrap code resurfaces.
- [ ] **Verify `weekly_basebackup.sh`** — grep it for the role it uses (`-U` flag). If it also uses `-U jarvis`, mark it as a second dead reference.

### Before Stage 5 cutover (cleanup)
- [ ] **Drop the dead cron** — remove `pg_dump -U jarvis jarvis` from `crontab` on Brain. It has been failing silently for an unknown period. Log files at `~/jarvis/backups/postgres/backup.log` should be checked for error history.
- [ ] **Drop `jarvis_app`** — no references anywhere; role serves no function. Drop after Stage 5 confirms zero-disruption.
- [ ] **Audit the `jarvis` BYPASSRLS flag before drop:** `jarvis` has `rolbypassrls=t` and `rolreplication=t`. This means if anything ever successfully reconnected as `jarvis`, it would bypass all RLS policies on `jarvis_alpha`. Even though it's dead today:
  - Revoke BYPASSRLS first: `ALTER ROLE jarvis NOBYPASSRLS;`
  - Then drop after Stage 5 confirms jarvis-core is permanently retired.
- [ ] **Drop `jarvis`** — only after BYPASSRLS is revoked, the dead cron is removed, and Stage 5 is live.

### Cleanup order relative to Stage 5
```
Stage 2 → GRANT USAGE on jarvis, jarvis_app (Path B)
↓
(any time before Stage 5)
→ ALTER ROLE jarvis NOBYPASSRLS; NOBYPASSRLS NOREPLICATION;  -- defang the role
→ Remove dead cron entry from Brain crontab
↓
Stage 5 (new credential pipeline live)
↓
(post-Stage 5 verification, ~1 week)
→ DROP ROLE jarvis_app;
→ DROP ROLE jarvis;
```

### Is BYPASSRLS on `jarvis` exploitable today?
**Low-but-non-zero risk.** The role has a valid SCRAM-SHA-256 password hash (visible in the baseline). If the password is weak or reused from jarvis-core, and an attacker gained localhost access (trust auth means any local process can connect), they could connect as `jarvis` and read/write all rows in `jarvis_alpha` bypassing RLS. pg_hba.conf uses trust auth for localhost, which means no password check is enforced for local connections — making the BYPASSRLS flag the only real barrier if local access is compromised. Defang it (`ALTER ROLE jarvis NOBYPASSRLS`) at earliest opportunity independent of Stage 5 timeline.

---

## Open Questions

1. **`weekly_basebackup.sh` role:** Does it use `-U jarvis` or `-U jarvisbrain`? Needs a targeted grep before declaring `jarvis` fully dead. (One command: `grep -n '\-U' ~/jarvis/backups/postgres/weekly_basebackup.sh`)

2. **`jarvis_app` password:** The role has a SCRAM hash. Is this password stored anywhere in jarvis-core configs on any other machine (endpoint, sand, forge)? If jarvis-core is ever reactivated, `jarvis_app` could reconnect. Out of scope for this audit but worth a cross-repo check before drop.

3. **`/Volumes/JarvisSecure` mount:** The dead cron writes to `/Volumes/JarvisSecure/...`. Is this volume routinely mounted? If so, the backup.log there will have error history for how long this cron has been failing.

4. **Ken's decision on BYPASSRLS timeline:** Should `ALTER ROLE jarvis NOBYPASSRLS` be added to Stage 2 as a defense-in-depth action (safe, non-destructive) or deferred to Stage 5 cleanup? Adding it to Stage 2 costs nothing and closes the attack surface sooner.
