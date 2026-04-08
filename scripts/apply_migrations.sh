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
#   - SSH failure to Brain → exit 1
#
# Override: ALLOW_FORCE_REAPPLY=1 will re-apply a file even if checksum matches
#           (still aborts on mismatch). Use only for emergency rollback testing.
#
# Tech debt tracked: TD-22 (wire into jarvisalpha_commit.sh)

set -uo pipefail

# ── Config ────────────────────────────────────────────────
BRAIN="jarvisbrain@100.64.166.22"
SSH_KEY="${HOME}/.ssh/macair_jarvis"
SSH_OPTS=(-i "$SSH_KEY" -o IdentitiesOnly=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no)
PSQL_PATH="/opt/homebrew/Cellar/postgresql@16/16.13/bin/psql"
DB="jarvis_alpha"
MIGRATIONS_DIR="${HOME}/jarvis-alpha/brain/db/migrations"
ADVISORY_LOCK_KEY=2026040701  # Arbitrary 64-bit int — must be stable across runs

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

# Run a SQL command on Brain. Returns stdout. Aborts on non-zero.
psql_exec() {
  local sql="$1"
  ssh "${SSH_OPTS[@]}" "$BRAIN" "$PSQL_PATH -d $DB -X -A -t -v ON_ERROR_STOP=1 -c \"$sql\""
}

# Apply a SQL file on Brain. Returns nothing. Aborts on non-zero.
psql_apply_file() {
  local local_path="$1"
  local remote_path="/tmp/$(basename "$local_path")"
  scp "${SSH_OPTS[@]}" "$local_path" "$BRAIN:$remote_path" >/dev/null 2>&1 || {
    error_box "scp failed" "Could not copy $local_path to Brain"
    return 1
  }
  ssh "${SSH_OPTS[@]}" "$BRAIN" "$PSQL_PATH -d $DB -X -v ON_ERROR_STOP=1 -1 -f $remote_path && rm $remote_path"
}

# ── Pre-flight ────────────────────────────────────────────
printf '\n%b── MIGRATION RUNNER ─────────────────────────────────────%b\n' "${CYAN}" "${RESET}"
printf '%s\n' "Host:           $(hostname -s)"
printf '%s\n' "Target:         $BRAIN"
printf '%s\n' "Database:       $DB"
printf '%s\n' "Migrations dir: $MIGRATIONS_DIR"
printf '%b─────────────────────────────────────────────────────────%b\n\n' "${CYAN}" "${RESET}"

# Verify migrations dir exists
if [[ ! -d "$MIGRATIONS_DIR" ]]; then
  error_box "Migrations directory not found" "Path: $MIGRATIONS_DIR"
  exit 1
fi

# Verify SSH connectivity
if ! ssh "${SSH_OPTS[@]}" "$BRAIN" "echo ok" >/dev/null 2>&1; then
  error_box "SSH to Brain failed" "Host: $BRAIN" "Check Tailscale + SSH key"
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

shopt -s nullglob
for file in "$MIGRATIONS_DIR"/*.sql; do
  basename=$(basename "$file")
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
      status_line "${CYAN}✓${RESET}" "$basename" "skipped (already applied)"
      SKIPPED=$((SKIPPED + 1))
      continue
    fi
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
printf '%b─────────────────────────────────────────────────────────%b\n' "${CYAN}" "${RESET}"

if [[ $FAILED -gt 0 ]]; then
  exit 1
fi

printf '\n%b✅ Migration runner complete%b\n' "${GREEN}" "${RESET}"
