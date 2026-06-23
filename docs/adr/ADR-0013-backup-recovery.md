# ADR-0013: Encrypted Postgres Backup + Proven Recovery for jarvis-alpha

**Repo (current):** `jarvis-alpha` (draft — for promotion to `jarvis-standards`)
**Status:** Proposed
**Date:** 2026-05-28
**Author:** Ken Haas (drafted with Claude Code)
**Supersedes:** None
**Related:** ADR-0015 (Mattermost ChatOps), INF-001 (broken SMB transport, Phase 0 audit P0)

---

## Context

Phase 0 production-readiness audit (`/tmp/alpha_audit_2026-05-27/`) classified
"no working Postgres backups" as a P0. The previous SMB-mount path on Brain
(INF-001) had been broken for approximately two months without detection. There
was no encrypted backup pipeline, no offsite copy, no restore drill, and no
observability into backup state. A correlated medical / family / approval-queue
data loss event under those conditions would have been unrecoverable.

This ADR records the design that closed that P0 in Session 1.

## Decision

1. **Transport: SSH/SCP, not SMB.** Brain → Unraid runs via a dedicated
   ed25519 keypair (`~/.ssh/jarvis_alpha_backup`), persisted in
   `/boot/config/ssh/root/authorized_keys` (Unraid 7.2.3 path) so the key
   survives reboots.
2. **Encryption: GPG symmetric AES256** with the passphrase passed to gpg via
   fd 3 only — never argv, never persistent env. `BACKUP_GPG_PASSPHRASE` is
   stored in `~/jarvis/.secrets` on Brain (mode 600).
3. **Storage layout on Unraid:** `/mnt/user/Backups/jarvis-alpha/{dumps,manifests}/`,
   files chmod 600. Atomic `.partial` → final rename after sha256 round-trip
   verify.
4. **Cadence:**
   - Nightly backup at 02:30 local on Brain (`com.jarvis.alpha.pg_backup`).
   - Weekly restore drill at Sunday 03:30 local on Sandbox
     (`com.jarvis.alpha.restore_drill`).
5. **Retention:** keep all dumps from the last 30 days, plus the first-of-month
   forever.
6. **Restore drill runs on Sandbox**, deliberately not on Brain — a real
   disaster recovery means Brain is unavailable; drilling on Sandbox proves
   that capability. The drill uses an ephemeral `pgvector/pgvector:pg16` Docker
   container, restored, verified against live Brain reference (table count + row
   counts on 4 anchor tables), and torn down whether the drill passes or fails.
7. **Observability via existing Mattermost surface (ADR-0015):**
   `mm_notify` + `buddy_event` helpers, inline in both scripts. Success →
   `#alpha-events` info; failure → `#alpha-events` + `#alerts` critical
   (gateway auto-routing by severity). Notification failures never block the
   backup pipeline.
8. **Scheduling via LaunchAgent templates** following the existing
   `school-email` pattern: `{{HOME}}` placeholder substituted at install time,
   `*.template.plist` tracked, `*.plist` gitignored. Templates live in
   `launchagents/`, installed via `scripts/install_launchagents.py --node <node>`.

## Why SSH over SMB

INF-001 documents that the Brain SMB mount silently broke and went undetected
for two months. Root cause for that brittleness:

- macOS SMB auto-mount behavior is opaque; a stale or expired credential
  fails silently and the mount point stays empty.
- The previous design assumed the mount; nothing actively probed end-to-end
  write capability.
- SMB credentials lived in macOS keychain, which is awkward to rotate and
  audit.

SSH/SCP gives us:

- An end-to-end probe (`ssh + stat + scp`) embedded in the preflight every run.
- Industry-standard credential handling: a dedicated keypair, removable by
  deleting a line in `authorized_keys`.
- A working channel that is independently usable for the restore drill from
  any node — not coupled to the macOS SMB stack.

## Consequences

### Positive

- **P0 closed.** Encrypted backups land nightly; recoverability is *proven*
  weekly by the drill rather than assumed.
- **RTO ~minutes.** Restore drill end-to-end is ~6 seconds for the current
  data volume (~11 MB encrypted, 3 DBs). Real DR adds image-pull and human
  decision time; the script path is sub-minute.
- **RPO 24h** by design (nightly cadence). Acceptable for current workload;
  reviewed in Reversal Conditions.
- **Observability matches existing Mattermost contract** — the operator does
  not have to watch two surfaces.

### Negative

- **`BACKUP_GPG_PASSPHRASE` now on 2 nodes** (Brain + Sandbox). This is the
  deliberate DR-readiness trade-off: in a real disaster you need the
  passphrase on whatever node performs recovery, so pre-positioning it on
  Sandbox is the readiness. Compensating controls: file mode 600 on both,
  passphrase never on argv/env, only fd 3.
- **`GATEWAY_TOKEN` now on Sandbox** for drill-failure notifications.
- **pgaudit not in the drill container.** `pgvector/pgvector:pg16` doesn't
  ship pgaudit, so `pg_restore` emits 1 expected error per `CREATE EXTENSION
  pgaudit` line. The drill explicitly counts pgaudit-only errors and treats
  them as ignorable; any non-pgaudit error fails the drill.
- **Total public relation count is a lower-bound sanity check.** Normal
  migrations add tables and views, so exact table-count drift is not a backup
  failure. Restore readiness is gated by named critical table probes, FORCE RLS
  counts, row probes, and non-pgaudit restore errors.

### Neutral

- Backup volume is small (~11 MB encrypted today) so the nightly window
  fits well inside 02:30–03:30 even under sustained growth.

## Sovereignty First Compliance

| Component | Tier | Fallback |
|---|---|---|
| `pg_dump` on Brain | Tier 1 self-hosted | Manual SQL dump |
| GPG symmetric encrypt | Tier 1 self-hosted (gnupg) | None (re-encrypt with new passphrase if compromised) |
| Unraid `/mnt/user/Backups` over SSH/SCP | Tier 1 self-hosted | Hot-spare USB on Brain (future) |
| Drill restore on OrbStack pgvector container | Tier 1 self-hosted | Re-run on Brain if Sandbox unavailable |
| Mattermost notification (ADR-0015) | Tier 1 self-hosted | Pushover fallback per ADR-0015 |

## Alternatives Considered

### SMB transport (INF-001's pattern)

Rejected. Two-month silent failure, opaque failure mode, brittle macOS
auto-mount semantics.

### WAL streaming for sub-24h RPO

Deferred to Alpha-6 candidate. Current RPO (24h) is acceptable for the
workload; WAL streaming adds a continuous replication daemon (likely
`pg_receivewal` on Unraid) plus integrity testing for partial WAL segments.
Worth doing once the family / financial / medical surfaces produce data with
meaningful intra-day value-at-risk.

### Cloud backup (S3 / Backblaze)

Rejected. Sovereignty First: ops control plane stays inside the Tailscale
mesh; offsite via second physical drive or partner-mirrored Unraid is the
acceptable expansion path.

### `wal-g` or `pgBackRest`

Considered. Overkill for current volume + cadence; would have added a stateful
daemon to maintain. Standard `pg_dump --format=custom` round-trips losslessly
into `pg_restore` and is the boring industrial baseline. Revisit if the data
volume crosses ~10 GB or RPO requirements tighten.

## Reversal Conditions

1. **Drill fails on a real backup more than once after stabilization.** That
   means backups are not actually recoverable; immediate root cause, no
   roll-forward.
2. **Drill duration exceeds the Sunday 03:30 window after data growth.** Need
   to either parallelize per-DB or move to streaming.
3. **RPO of 24h becomes inadequate** (e.g. medical surface starts producing
   irreplaceable intraday data) → WAL streaming path.
4. **Passphrase compromise on either node** → rotate passphrase, re-encrypt
   the entire retained set under the new key, expire the old. Existing
   first-of-month retention makes this tractable.

## References

- Phase 0 audit deliverables: `/tmp/alpha_audit_2026-05-27/*.md`
- `scripts/pg_backup_alpha.sh` — main backup script
- `scripts/preflight_brain_backup.sh` — preflight checks
- `scripts/restore_drill_alpha.sh` — DR drill
- `launchagents/com.jarvis.alpha.pg_backup.template.plist`
- `launchagents/com.jarvis.alpha.restore_drill.template.plist`
- `tests/test_backup_scripts.py` — static + retention algorithm guards
- ADR-0015 (Mattermost ChatOps surface)
