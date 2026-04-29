#!/usr/bin/env bash
# scripts/configure_pgaudit.sh
# Idempotently configure postgresql.conf for pgAudit + log rotation.
# Slab 1 of RLS Foundation Step 7.
#
# Writes a managed block bracketed by BEGIN/END PGAUDIT_MANAGED markers.
# Re-running replaces the block in place — safe + idempotent.
# Backs up postgresql.conf with timestamp before any change.
# Validates with `postgres --check-config` before declaring done.
# Does NOT restart Postgres — that is a manual step with timing control.
#
# Override defaults via env:
#   PG_CONFIG_PATH=/path/to/pg_config
#   PG_DATA_DIR=/opt/homebrew/var/postgresql@16

set -euo pipefail

PG_CONFIG_PATH="${PG_CONFIG_PATH:-/opt/homebrew/Cellar/postgresql@16/16.13/bin/pg_config}"
POSTGRES_BIN_DEFAULT="$(dirname "$PG_CONFIG_PATH")/postgres"
POSTGRES_BIN="${POSTGRES_BIN:-$POSTGRES_BIN_DEFAULT}"

BEGIN_MARKER="# BEGIN PGAUDIT_MANAGED — do not edit between markers; managed by scripts/configure_pgaudit.sh"
END_MARKER="# END PGAUDIT_MANAGED"

log() {
  printf '{"timestamp":"%s","level":"info","service":"configure_pgaudit","node":"brain","message":"%s"}\n' \
    "$(date -u +%FT%TZ)" "$1"
}

fail() {
  printf '{"timestamp":"%s","level":"error","service":"configure_pgaudit","node":"brain","message":"%s"}\n' \
    "$(date -u +%FT%TZ)" "$1" >&2
  exit 1
}

[[ -x "$PG_CONFIG_PATH" ]] || fail "pg_config not executable at $PG_CONFIG_PATH"
[[ -x "$POSTGRES_BIN" ]] || fail "postgres binary not executable at $POSTGRES_BIN"

# Discover data dir
if [[ -n "${PG_DATA_DIR:-}" ]]; then
  DATA_DIR="$PG_DATA_DIR"
else
  # Homebrew default
  DATA_DIR="/opt/homebrew/var/postgresql@16"
fi
[[ -d "$DATA_DIR" ]] || fail "postgres data dir not found at $DATA_DIR (set PG_DATA_DIR)"

CONF_FILE="$DATA_DIR/postgresql.conf"
[[ -f "$CONF_FILE" ]] || fail "postgresql.conf not found at $CONF_FILE"

log "data_dir=$DATA_DIR conf=$CONF_FILE"

# Backup
TS="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="$CONF_FILE.backup_$TS"
cp -p "$CONF_FILE" "$BACKUP"
log "backup_written path=$BACKUP"

# Build managed block
MANAGED_BLOCK=$(cat <<'EOF'
# BEGIN PGAUDIT_MANAGED — do not edit between markers; managed by scripts/configure_pgaudit.sh
# Slab 1 of RLS Foundation Step 7 — Apr 2026

# pgAudit extension
shared_preload_libraries = 'pgaudit'
pgaudit.log = 'role, ddl, write'
pgaudit.log_catalog = off
pgaudit.log_relation = on
pgaudit.log_parameter = off
pgaudit.log_statement = on
pgaudit.log_level = log

# Log rotation policy
log_rotation_size = 100MB
log_rotation_age = '90d'
log_truncate_on_rotation = off
# END PGAUDIT_MANAGED
EOF
)

# Strip any existing managed block (idempotent re-run)
TMP_CONF="$(mktemp)"
trap 'rm -f "$TMP_CONF"' EXIT

awk -v begin="# BEGIN PGAUDIT_MANAGED" -v end="# END PGAUDIT_MANAGED" '
  $0 ~ begin { skip = 1; next }
  $0 ~ end   { skip = 0; next }
  !skip      { print }
' "$CONF_FILE" > "$TMP_CONF"

# Append fresh block (separated by single blank line)
{
  cat "$TMP_CONF"
  echo
  echo "$MANAGED_BLOCK"
} > "$TMP_CONF.new"

# Validate before swap
log "validating new conf"
if ! "$POSTGRES_BIN" -D "$DATA_DIR" -c "config_file=$TMP_CONF.new" -C shared_preload_libraries >/dev/null 2>&1; then
  CHECK_OUT=$("$POSTGRES_BIN" -D "$DATA_DIR" -c "config_file=$TMP_CONF.new" -C shared_preload_libraries 2>&1 || true)
  rm -f "$TMP_CONF.new"
  fail "postgres --check-config rejected new conf: $CHECK_OUT"
fi
log "validation_passed"

# Atomic swap
mv "$TMP_CONF.new" "$CONF_FILE"
log "conf_written path=$CONF_FILE"

# Diff summary against backup (informational)
DIFF_LINES=$(diff "$BACKUP" "$CONF_FILE" | wc -l | tr -d ' ')
log "diff_lines=$DIFF_LINES vs $BACKUP"

echo "=== configure_pgaudit.sh complete ==="
echo "conf=$CONF_FILE"
echo "backup=$BACKUP"
echo "managed block: BEGIN PGAUDIT_MANAGED ... END PGAUDIT_MANAGED"
echo "next_step: stop services in order, then 'brew services restart postgresql@16', then run install migration"
