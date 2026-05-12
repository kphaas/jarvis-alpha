#!/bin/bash
# apply_migrations.sh — Canonical migration runner for jarvis_alpha
#
# Behavior:
#   1. Acquires advisory lock (prevents concurrent runs)
#   2. Lists all *.sql files in brain/db/migrations/ in lexical order
#   3. For each file:
#      - Computes SHA-256 checksum
#      - Checks schema_migrations table
#      - If filename present + checksum matches → skip
#      - If filename present + checksum mismatch → ABORT (file was edited)
#      - If filename absent → apply file in single transaction, record in tracking table
#   4. Releases lock, prints summary
#
# Loud failure semantics:
#   - Any psql error → exit 1 with error_box
#   - Checksum mismatch → exit 1 with error_box
#   - Local DB failure → exit 1
#
# Override: ALLOW_FORCE_REAPPLY=1 will re-apply a file even if checksum matches
#           (still aborts on mismatch). Use only for emergency rollback testing.
#
# Tech debt tracked: TD-22 (wire into jarvisalpha_commit.sh)

set -uo pipefail

# ── Config ────────────────────────────────────────────────
PSQL_PATH="/opt/homebrew/Cellar/postgresql@16/16.13/bin/psql"
DB="${DB:-jarvis_alpha}"
MIGRATIONS_DIR="${HOME}/jarvis-alpha/brain/db/migrations"
ADVISORY_LOCK_KEY=2026040701  # Arbitrary 64-bit int — must be stable across runs

# TD-X40 backfill mode — opt-in path to record on-disk migrations as
# already-applied without executing them. Use when bootstrapping a fresh
# DB from a SQL dump where objects already exist.
ALLOW_BACKFILL="${ALLOW_BACKFILL:-0}"
CONFIRM_BACKFILL="${CONFIRM_BACKFILL:-0}"
I_KNOW_THIS_IS_PROD="${I_KNOW_THIS_IS_PROD:-0}"

if [ "$(hostname -s)" != "jarvis-brain" ]; then
  echo "❌ apply_migrations.sh must run on Brain (jarvis-brain). Current host: $(hostname -s)"
  exit 1
fi

# ── Colors ────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

# ── Helpers ───────────────────────────────────────────────
status_line() {
  local icon="$1"
  local label="$2"
  local detail="$3"
  printf '%b  %-40s %b\n' "$icon" "$label" "$detail"
}

error_box() {
  local title="$1"
  shift
  printf '%b\n' "${RED}${BOLD}╔════════════════════════════════════════════════════════╗${RESET}" >&2
  printf '%b%b ❌ %s%b\n' "${RED}${BOLD}║${RESET}" "${RED}${BOLD}" "$title" "${RESET}" >&2
  for line in "$@"; do
    printf '%b   %s\n' "${RED}${BOLD}║${RESET}" "$line" >&2
  done
  printf '%b\n' "${RED}${BOLD}╚════════════════════════════════════════════════════════╝${RESET}" >&2
}

# Run a SQL command locally. Returns stdout. Aborts on non-zero.
psql_exec() {
  local sql="$1"
  "$PSQL_PATH" -d "$DB" -X -A -t -v ON_ERROR_STOP=1 -c "$sql"
}

# Apply a SQL file locally. Returns nothing. Aborts on non-zero.
psql_apply_file() {
  local file="$1"
  "$PSQL_PATH" -d "$DB" -X -v ON_ERROR_STOP=1 -1 -f "$file"
}

# ── Pre-flight ────────────────────────────────────────────
printf '\n%b── MIGRATION RUNNER ─────────────────────────────────────%b\n' "${CYAN}" "${RESET}"
printf '%s\n' "Host:           $(hostname -s)"
printf '%s\n' "Database:       $DB"
printf '%s\n' "Migrations dir: $MIGRATIONS_DIR"
printf '%s\n' "─────────────────────────────────────────────────────────"
printf '\n'

# Verify migrations dir exists
if [[ ! -d "$MIGRATIONS_DIR" ]]; then
  error_box "Migrations directory not found" "Path: $MIGRATIONS_DIR"
  exit 1
fi

# Verify local psql connectivity
if ! "$PSQL_PATH" -d "$DB" -X -A -t -c "SELECT 1;" >/dev/null 2>&1; then
  echo "❌ Cannot connect to local Postgres database: $DB"
  exit 1
fi

# Verify schema_migrations table exists
TABLE_EXISTS=$(psql_exec "SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename='schema_migrations';" 2>/dev/null || echo "")
if [[ -z "$TABLE_EXISTS" ]]; then
  error_box "schema_migrations table not found" \
    "Bootstrap required — apply this file manually first:" \
    "psql -d $DB -f <create_schema_migrations.sql>"
  exit 1
fi

# ── Backfill mode validation (TD-X40) ─────────────────────
if [ "$ALLOW_BACKFILL" = "1" ]; then
  if [ "${ALLOW_FORCE_REAPPLY:-0}" = "1" ]; then
    error_box "ALLOW_BACKFILL and ALLOW_FORCE_REAPPLY are mutually exclusive" \
      "Pick one: backfill (record without applying) or force-reapply (re-run a tracked file)."
    exit 1
  fi
  if [ "$DB" != "jarvis_alpha_test" ] && [ "$I_KNOW_THIS_IS_PROD" != "1" ]; then
    error_box "BACKFILL mode against non-test DB '$DB' requires I_KNOW_THIS_IS_PROD=1" \
      "Set I_KNOW_THIS_IS_PROD=1 to acknowledge that backfill rows will land in '$DB'."
    exit 1
  fi
  printf '%b\n' "${YELLOW}════════════════════════════════════════════${RESET}"
  printf '%b  BACKFILL MODE ACTIVE%b\n' "${YELLOW}${BOLD}" "${RESET}"
  printf '%b  DB: %s%b\n' "${YELLOW}" "$DB" "${RESET}"
  if [ "$CONFIRM_BACKFILL" = "1" ]; then
    printf '%b  Mode: WRITE (CONFIRM_BACKFILL=1)%b\n' "${RED}${BOLD}" "${RESET}"
  else
    printf '%b  Mode: DRY-RUN (set CONFIRM_BACKFILL=1 to write)%b\n' "${CYAN}" "${RESET}"
  fi
  printf '%b════════════════════════════════════════════%b\n' "${YELLOW}" "${RESET}"
fi

# ── Acquire advisory lock ─────────────────────────────────
LOCK_OUT=$(psql_exec "SELECT pg_try_advisory_lock($ADVISORY_LOCK_KEY);" 2>&1)
if [[ "$LOCK_OUT" != "t" ]]; then
  error_box "Could not acquire advisory lock" \
    "Another runner instance may be active" \
    "Lock key: $ADVISORY_LOCK_KEY" \
    "If stuck: psql -d $DB -c \"SELECT pg_advisory_unlock($ADVISORY_LOCK_KEY);\""
  exit 1
fi
printf '%b\n' "${GREEN}✅ Advisory lock acquired (key=$ADVISORY_LOCK_KEY)${RESET}"

# Cleanup function — always release lock on exit
cleanup() {
  psql_exec "SELECT pg_advisory_unlock($ADVISORY_LOCK_KEY);" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# ── Main loop ─────────────────────────────────────────────
APPLIED=0
SKIPPED=0
FAILED=0
BACKFILL_APPLIED=0
BACKFILL_DRY_RUN=0

shopt -s nullglob
for file in "$MIGRATIONS_DIR"/*.sql; do
  basename=$(basename "$file")

  # TD-184: defense-in-depth — skip rollback files even if accidentally placed here.
  # Canonical home is brain/db/rollbacks/ (per TD-183 self-cancelling deploy recovery).
  if [[ "$basename" == *_rollback.sql ]]; then
    echo "  [SKIP] $basename — rollback files belong in brain/db/rollbacks/"
    continue
  fi

  local_checksum=$(shasum -a 256 "$file" | awk '{print $1}')

  # Check if already in tracking table
  recorded=$(psql_exec "SELECT checksum FROM schema_migrations WHERE filename='$basename';" 2>/dev/null || echo "")

  if [[ -n "$recorded" ]]; then
    # File already applied — verify checksum
    if [[ "$recorded" != "$local_checksum" ]]; then
      if [[ "${ALLOW_FORCE_REAPPLY:-0}" != "1" ]]; then
        error_box "CHECKSUM MISMATCH on $basename" \
          "Recorded:  $recorded" \
          "Computed:  $local_checksum" \
          "An applied migration file has been edited. This is forbidden." \
          "If intentional, set ALLOW_FORCE_REAPPLY=1 (dangerous)."
        FAILED=$((FAILED + 1))
        exit 1
      fi
      printf '%b\n' "${YELLOW}⚠️  Force re-applying $basename (ALLOW_FORCE_REAPPLY=1)${RESET}"
    else
      if [[ "${VERBOSE:-0}" == "1" ]]; then
        status_line "${CYAN}✓${RESET}" "$basename" "skipped (already applied)"
      fi
      SKIPPED=$((SKIPPED + 1))
      continue
    fi
  fi

  # TD-X40: backfill short-circuit — record as already-applied without running.
  # NOTE: schema_migrations.source CHECK constraint allows {runner, pre-tracking,
  # baseline}. 'backfill' is the user-facing mode name (ALLOW_BACKFILL=1); the
  # recorded DB source is 'baseline' since that's the schema-allowed value
  # semantically closest to "recording an existing baseline state".
  if [ "$ALLOW_BACKFILL" = "1" ]; then
    if [ "$CONFIRM_BACKFILL" = "1" ]; then
      if ! psql_exec "INSERT INTO schema_migrations (filename, checksum, execution_time_ms, source) VALUES ('$basename', '$local_checksum', 0, 'baseline') ON CONFLICT (filename) DO UPDATE SET checksum=EXCLUDED.checksum, source=EXCLUDED.source, applied_at=NOW();" >/dev/null; then
        error_box "Failed to backfill $basename in schema_migrations" \
          "Manually insert: filename=$basename checksum=$local_checksum source=backfill"
        FAILED=$((FAILED + 1))
        exit 1
      fi
      printf '[BACKFILL APPLIED] %s (%s)\n' "$basename" "$local_checksum" >&2
      BACKFILL_APPLIED=$((BACKFILL_APPLIED + 1))
    else
      printf '[BACKFILL DRY-RUN] would backfill: %s (%s)\n' "$basename" "$local_checksum" >&2
      BACKFILL_DRY_RUN=$((BACKFILL_DRY_RUN + 1))
    fi
    continue
  fi

  # New migration — apply it
  status_line "${YELLOW}→${RESET}" "$basename" "applying..."
  # macOS date does not support %3N; always use Python for sub-second ms.
  start_ms=$(python3 -c 'import time; print(int(time.time()*1000))')

  if ! psql_apply_file "$file"; then
    error_box "Migration failed: $basename" \
      "Stopping. Previous migrations remain committed." \
      "Fix the file and re-run."
    FAILED=$((FAILED + 1))
    exit 1
  fi

  end_ms=$(python3 -c 'import time; print(int(time.time()*1000))')
  duration_ms=$((end_ms - start_ms))

  # Record in tracking table — escape single quotes in checksum (none expected, but defensive)
  if ! psql_exec "INSERT INTO schema_migrations (filename, checksum, execution_time_ms, source) VALUES ('$basename', '$local_checksum', $duration_ms, 'runner') ON CONFLICT (filename) DO UPDATE SET checksum=EXCLUDED.checksum, applied_at=NOW(), execution_time_ms=EXCLUDED.execution_time_ms;" >/dev/null; then
    error_box "Failed to record $basename in schema_migrations" \
      "Migration WAS applied successfully but tracking record failed." \
      "Manually insert: filename=$basename checksum=$local_checksum"
    FAILED=$((FAILED + 1))
    exit 1
  fi

  status_line "${GREEN}✅${RESET}" "$basename" "applied (${duration_ms}ms)"
  APPLIED=$((APPLIED + 1))
done
shopt -u nullglob

# ── Summary ───────────────────────────────────────────────
printf '\n%b── SUMMARY ──────────────────────────────────────────────%b\n' "${CYAN}" "${RESET}"
printf '  Applied:  %d\n' "$APPLIED"
printf '  Skipped:  %d\n' "$SKIPPED"
printf '  Failed:   %d\n' "$FAILED"
if [ "$ALLOW_BACKFILL" = "1" ]; then
  printf '  Backfill applied: %d\n' "$BACKFILL_APPLIED"
  printf '  Backfill dry-run: %d\n' "$BACKFILL_DRY_RUN"
fi
printf '%b─────────────────────────────────────────────────────────%b\n' "${CYAN}" "${RESET}"

if [[ $FAILED -gt 0 ]]; then
  exit 1
fi

printf '\n%b✅ Migration runner complete%b\n' "${GREEN}" "${RESET}"
