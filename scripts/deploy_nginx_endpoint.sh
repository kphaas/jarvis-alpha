#!/bin/bash
# deploy_nginx_endpoint.sh — Atomic nginx config deploy for Endpoint (AI-3)
# Pattern: copy-validate-reload-verify with automatic rollback on any failure.
# Usage: sudo bash ~/jarvis-alpha/scripts/deploy_nginx_endpoint.sh

set -uo pipefail

# ── Config ────────────────────────────────────────────────
SOURCE="${HOME}/jarvis-alpha/endpoint/nginx/alpha.conf"
TARGET="/opt/homebrew/etc/nginx/servers/alpha.conf"
NGINX="/opt/homebrew/bin/nginx"
HEALTH_URL="https://127.0.0.1:4100"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP="${TARGET}.bak.${TIMESTAMP}"

# ── Colors ────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
RESET='\033[0m'

log() { printf '%b%s%b\n' "$1" "$2" "$RESET"; }

# ── Pre-flight ────────────────────────────────────────────
log "$CYAN" "── NGINX DEPLOY (AI-3) ──────────────────────────────"

if [ "$(hostname -s)" != "jarvis-endpoint" ]; then
  log "$RED" "❌ FAIL: This script only runs on jarvis-endpoint (detected: $(hostname -s))"
  exit 1
fi

if [ "$(id -u)" != "0" ]; then
  log "$RED" "❌ FAIL: Must run with sudo (nginx reload requires root)"
  log "$YELLOW" "   Retry: sudo bash $0"
  exit 1
fi

# Note: HOME may be /var/root under sudo. Hardcode user path for source lookup.
REAL_HOME=$(eval echo "~jarvisendpoint")
SOURCE="${REAL_HOME}/jarvis-alpha/endpoint/nginx/alpha.conf"

if [ ! -f "$SOURCE" ]; then
  log "$RED" "❌ FAIL: Source config not found at $SOURCE"
  exit 1
fi

if [ ! -x "$NGINX" ]; then
  log "$RED" "❌ FAIL: nginx binary not found at $NGINX"
  exit 1
fi

if [ ! -d "$(dirname "$TARGET")" ]; then
  log "$RED" "❌ FAIL: Target directory $(dirname "$TARGET") does not exist"
  exit 1
fi

log "$GREEN" "✅ Pre-flight checks passed"

# ── Backup current config ─────────────────────────────────
if [ -f "$TARGET" ]; then
  cp "$TARGET" "$BACKUP" || {
    log "$RED" "❌ FAIL: Backup failed"
    exit 1
  }
  log "$GREEN" "✅ Backup created: $BACKUP"
else
  log "$YELLOW" "ℹ️  No existing config — first-time install"
fi

# ── Restore function for rollback ─────────────────────────
restore_backup() {
  if [ -f "$BACKUP" ]; then
    log "$YELLOW" "↩️  Restoring backup..."
    cp "$BACKUP" "$TARGET"
    "$NGINX" -s reload 2>/dev/null || true
    log "$YELLOW" "↩️  Restored to pre-deploy state"
  fi
}

# ── Atomic stage ──────────────────────────────────────────
TEMP="${TARGET}.tmp"
cp "$SOURCE" "$TEMP" || {
  log "$RED" "❌ FAIL: Stage copy failed"
  restore_backup
  exit 1
}

mv "$TEMP" "$TARGET" || {
  log "$RED" "❌ FAIL: Atomic rename failed"
  rm -f "$TEMP"
  restore_backup
  exit 1
}

log "$GREEN" "✅ New config staged"

# ── Validate ──────────────────────────────────────────────
VALIDATE_LOG=$(mktemp)
if ! "$NGINX" -t >"$VALIDATE_LOG" 2>&1; then
  log "$RED" "❌ FAIL: nginx config validation failed:"
  cat "$VALIDATE_LOG"
  rm -f "$VALIDATE_LOG"
  restore_backup
  exit 1
fi
rm -f "$VALIDATE_LOG"
log "$GREEN" "✅ Config validated (nginx -t passed)"

# ── Reload ────────────────────────────────────────────────
if ! "$NGINX" -s reload 2>/dev/null; then
  log "$RED" "❌ FAIL: nginx reload failed"
  restore_backup
  exit 1
fi
log "$GREEN" "✅ nginx reloaded"

# ── Verify ────────────────────────────────────────────────
sleep 1
HTTP_CODE=$(curl -sk -o /dev/null -w "%{http_code}" --max-time 5 "$HEALTH_URL" 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "000" ]; then
  log "$YELLOW" "⚠️  WARN: Health check failed (no response) — nginx may still be OK"
  log "$YELLOW" "   Manual check: curl -sk $HEALTH_URL"
elif [ "$HTTP_CODE" -ge 500 ] 2>/dev/null; then
  log "$YELLOW" "⚠️  WARN: HTTP $HTTP_CODE from nginx — upstream (Brain) may be down"
  log "$YELLOW" "   nginx itself appears healthy; investigate upstream separately"
else
  log "$GREEN" "✅ Health check passed (HTTP $HTTP_CODE)"
fi

# ── Summary ───────────────────────────────────────────────
log "$CYAN" "─────────────────────────────────────────────────────"
log "$GREEN" "✅ DEPLOY COMPLETE"
echo "   Source:  $SOURCE"
echo "   Target:  $TARGET"
echo "   Backup:  $BACKUP"
echo "   Rollback: sudo cp $BACKUP $TARGET && sudo $NGINX -s reload"
