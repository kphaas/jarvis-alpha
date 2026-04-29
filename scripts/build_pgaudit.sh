#!/usr/bin/env bash
# scripts/build_pgaudit.sh
# Build + install pgAudit extension from source.
# Idempotent. Designed to re-run after Postgres minor upgrades.
# Slab 1 of RLS Foundation Step 7.
#
# Override defaults via env:
#   PGAUDIT_REF=REL_16_STABLE   (branch or tag)
#   PG_CONFIG_PATH=/path/to/pg_config
#   BUILD_ROOT=$HOME/jarvis/build

set -euo pipefail

PGAUDIT_REF="${PGAUDIT_REF:-REL_16_STABLE}"
PG_CONFIG_PATH="${PG_CONFIG_PATH:-/opt/homebrew/Cellar/postgresql@16/16.13/bin/pg_config}"
BUILD_ROOT="${BUILD_ROOT:-$HOME/jarvis/build}"
SOURCE_DIR="$BUILD_ROOT/pgaudit"
LOG_FILE="$BUILD_ROOT/build_pgaudit.log"

log() {
  printf '{"timestamp":"%s","level":"info","service":"build_pgaudit","node":"brain","message":"%s"}\n' \
    "$(date -u +%FT%TZ)" "$1" | tee -a "$LOG_FILE"
}

fail() {
  printf '{"timestamp":"%s","level":"error","service":"build_pgaudit","node":"brain","message":"%s"}\n' \
    "$(date -u +%FT%TZ)" "$1" >&2
  exit 1
}

mkdir -p "$BUILD_ROOT"

# Pre-flight
[[ -x "$PG_CONFIG_PATH" ]] || fail "pg_config not executable at $PG_CONFIG_PATH"
command -v git >/dev/null || fail "git not found"
command -v make >/dev/null || fail "make not found"

PG_VERSION=$("$PG_CONFIG_PATH" --version | awk '{print $2}')
PKGLIBDIR=$("$PG_CONFIG_PATH" --pkglibdir)
SHAREDIR=$("$PG_CONFIG_PATH" --sharedir)
EXTENSION_DIR="$SHAREDIR/extension"

log "postgres_version=$PG_VERSION pkglibdir=$PKGLIBDIR sharedir=$SHAREDIR"

# Sudo only if install paths not user-writable
if [[ -w "$PKGLIBDIR" && -w "$EXTENSION_DIR" ]]; then
  SUDO=""
  log "install paths user-writable, no sudo"
else
  SUDO="sudo"
  log "install paths require sudo"
fi

# Source: clone or update
if [[ -d "$SOURCE_DIR/.git" ]]; then
  log "fetching pgaudit refs"
  git -C "$SOURCE_DIR" fetch --tags --prune --quiet
else
  log "cloning pgaudit"
  git clone --quiet https://github.com/pgaudit/pgaudit.git "$SOURCE_DIR"
fi

git -C "$SOURCE_DIR" checkout --quiet "$PGAUDIT_REF"
git -C "$SOURCE_DIR" pull --ff-only --quiet origin "$PGAUDIT_REF" 2>/dev/null || true
HEAD_SHA=$(git -C "$SOURCE_DIR" rev-parse --short HEAD)
log "checked_out ref=$PGAUDIT_REF sha=$HEAD_SHA"

# Build
log "building"
make -C "$SOURCE_DIR" clean USE_PGXS=1 PG_CONFIG="$PG_CONFIG_PATH" >>"$LOG_FILE" 2>&1
make -C "$SOURCE_DIR" USE_PGXS=1 PG_CONFIG="$PG_CONFIG_PATH" >>"$LOG_FILE" 2>&1
log "build_complete"

# Install
log "installing"
$SUDO make -C "$SOURCE_DIR" install USE_PGXS=1 PG_CONFIG="$PG_CONFIG_PATH" >>"$LOG_FILE" 2>&1
log "install_complete"

# Verify install artifacts
SO_FOUND=""
for f in "$PKGLIBDIR/pgaudit.so" "$PKGLIBDIR/pgaudit.dylib"; do
  [[ -f "$f" ]] && SO_FOUND="$f" && break
done
[[ -n "$SO_FOUND" ]] || fail "pgaudit shared library not found in $PKGLIBDIR"

[[ -f "$EXTENSION_DIR/pgaudit.control" ]] || fail "pgaudit.control missing in $EXTENSION_DIR"

SQL_COUNT=$(find "$EXTENSION_DIR" -maxdepth 1 -name 'pgaudit--*.sql' | wc -l | tr -d ' ')
[[ "$SQL_COUNT" -gt 0 ]] || fail "no pgaudit--*.sql files in $EXTENSION_DIR"

log "verify_passed lib=$SO_FOUND sql_files=$SQL_COUNT"
log "next_steps: configure_pgaudit.sh, restart postgres, run install migration"

echo "=== build_pgaudit.sh complete ==="
echo "ref=$PGAUDIT_REF sha=$HEAD_SHA"
echo "library=$SO_FOUND"
echo "extension_dir=$EXTENSION_DIR"
echo "log=$LOG_FILE"
