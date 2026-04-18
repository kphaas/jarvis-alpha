#!/bin/bash
set -uo pipefail

REPO_DIR="${HOME}/jarvis-alpha"

# ── Event emitter (structured JSON events on stderr, parsed by commit script) ──
emit_event() {
  local json="$1"
  printf '##EVT##%s\n' "$json" >&2
}

time_ms() {
  python3 -c 'import time; print(int(time.time() * 1000))'
}

# ── Event helper: takes phase + node + inline field list ──
# Usage: emit ok pull node=brain from_hash=abc to_hash=def file_count=2 dur_ms=800
emit() {
  local status="$1"; shift
  local phase="$1"; shift
  local fields="\"status\":\"$status\",\"phase\":\"$phase\""
  for kv in "$@"; do
    local k="${kv%%=*}"
    local v="${kv#*=}"
    if [[ "$v" =~ ^[0-9]+$ ]]; then
      fields+=",\"$k\":$v"
    else
      # Escape quotes in string values
      v="${v//\"/\\\"}"
      fields+=",\"$k\":\"$v\""
    fi
  done
  emit_event "{$fields}"
}

# Node identifier for events — short hostname (brain / gateway / endpoint)
NODE_SHORT="$(hostname -s | sed 's/jarvis-//')"
DEPLOY_START_MS=$(time_ms)

if [ -f "${HOME}/jarvis/.secrets" ]; then
  SECRETS_FILE="${HOME}/jarvis/.secrets"
else
  SECRETS_FILE="${HOME}/.secrets"
fi

echo ""
echo "── JARVIS-ALPHA PULL ────────────────────────────────────"
echo "Node: $(hostname)"
echo "Time: $(date '+%Y-%m-%d %H:%M')"
echo ""

if [ ! -f "$SECRETS_FILE" ]; then
  echo "ERROR: secrets file not found at $SECRETS_FILE"
  exit 1
fi

set -a
source "$SECRETS_FILE"
set +a

if [ -z "${GITHUB_TOKEN:-}" ]; then
  echo "ERROR: GITHUB_TOKEN not set in secrets"
  exit 1
fi

if [ ! -d "$REPO_DIR" ]; then
  echo "Cloning jarvis-alpha for first time..."
  if ! git clone https://kphaas:${GITHUB_TOKEN}@github.com/kphaas/jarvis-alpha.git "$REPO_DIR"; then
    echo ""
    echo "❌ GIT CLONE FAILED — aborting."
    exit 1
  fi
else
  cd "$REPO_DIR"
  PREV_HEAD=$(git rev-parse --short HEAD 2>/dev/null || echo "")
  git config credential.helper ""
  GIT_TERMINAL_PROMPT=0 git remote set-url origin https://kphaas:${GITHUB_TOKEN}@github.com/kphaas/jarvis-alpha.git

  PULL_START=$(time_ms)
  if ! GIT_TERMINAL_PROMPT=0 git pull origin main --rebase; then
    PULL_DUR=$(($(time_ms) - PULL_START))
    emit fail pull node="$NODE_SHORT" from_hash="$PREV_HEAD" dur_ms="$PULL_DUR" error="git pull rebase failed"
    echo ""
    echo "❌ GIT PULL FAILED — aborting."
    echo "   Check: cd $REPO_DIR && git status"
    exit 1
  fi
  PULL_DUR=$(($(time_ms) - PULL_START))
fi

NEW_HEAD=$(git -C "$REPO_DIR" rev-parse --short HEAD)

# Count files changed in this pull (0 if no-op pull)
if [ -n "${PREV_HEAD:-}" ] && [ "$PREV_HEAD" != "$NEW_HEAD" ]; then
  FILE_COUNT=$(git -C "$REPO_DIR" diff --name-only "${PREV_HEAD}..${NEW_HEAD}" | wc -l | tr -d ' ')
else
  FILE_COUNT=0
fi
emit ok pull node="$NODE_SHORT" from_hash="${PREV_HEAD:-none}" to_hash="$NEW_HEAD" file_count="$FILE_COUNT" dur_ms="$PULL_DUR"

if [ -n "${PREV_HEAD:-}" ] && [ "$PREV_HEAD" != "$NEW_HEAD" ]; then
  echo ""
  echo "── INCOMING COMMITS ─────────────────────────────────────"
  git -C "$REPO_DIR" log --no-merges --pretty=format:'%h  %s  (%an, %ar)' "${PREV_HEAD}..${NEW_HEAD}"
  echo ""
  echo ""
  echo "── CHURN ────────────────────────────────────────────────"
  git -C "$REPO_DIR" diff --shortstat "${PREV_HEAD}..${NEW_HEAD}"
  git -C "$REPO_DIR" diff --stat "${PREV_HEAD}..${NEW_HEAD}" | tail -n +1 | head -n 20
fi

echo ""
echo "✅ jarvis-alpha pulled — $NEW_HEAD"
echo "─────────────────────────────────────────────────────────"

echo ""
if [ "$(hostname -s)" = "jarvis-brain" ]; then
  echo "Running database migrations..."
  MIG_START=$(time_ms)
  MIG_LOG=$(mktemp)
  if ! bash "${REPO_DIR}/scripts/apply_migrations.sh" 2>&1 | tee "$MIG_LOG"; then
    MIG_DUR=$(($(time_ms) - MIG_START))
    MIG_ERR=$(tail -3 "$MIG_LOG" | tr '\n' ' ')
    rm -f "$MIG_LOG"
    emit fail migration node="$NODE_SHORT" dur_ms="$MIG_DUR" error="$MIG_ERR"
    echo ""
    echo "❌ MIGRATION FAILED — aborting pull deploy."
    echo "   Services NOT restarted. Fix migration before retrying."
    exit 1
  fi
  echo "✅ Migrations applied"
  # Parse applied/skipped/failed from migration runner output
  MIG_APPLIED=$(grep -E "Applied:" "$MIG_LOG" | grep -oE "[0-9]+" | head -1 || echo 0)
  MIG_SKIPPED=$(grep -E "Skipped:" "$MIG_LOG" | grep -oE "[0-9]+" | head -1 || echo 0)
  MIG_FAILED=$(grep -E "Failed:" "$MIG_LOG" | grep -oE "[0-9]+" | head -1 || echo 0)
  MIG_DUR=$(($(time_ms) - MIG_START))
  rm -f "$MIG_LOG"
  emit ok migration node="$NODE_SHORT" applied="$MIG_APPLIED" skipped="$MIG_SKIPPED" failed="$MIG_FAILED" dur_ms="$MIG_DUR"
else
  echo "ℹ️  Skipping migrations — not on Brain (host: $(hostname -s))"
  emit skip migration node="$NODE_SHORT"
fi
echo ""

BRAIN_PLIST="${HOME}/Library/LaunchAgents/com.jarvis.alpha.brain.plist"
if [ -f "$BRAIN_PLIST" ]; then
  echo ""
  echo "Restarting Alpha Brain LaunchAgent..."

  PYCACHE_START=$(time_ms)
  launchctl unload "$BRAIN_PLIST" 2>/dev/null || true
  sleep 1
  lsof -ti :8186 | xargs kill -9 2>/dev/null || true
  sleep 2
  find "${REPO_DIR}/brain" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
  emit ok pycache node="$NODE_SHORT" dur_ms=$(($(time_ms) - PYCACHE_START))

  RESTART_START=$(time_ms)
  launchctl load "$BRAIN_PLIST"
  sleep 4
  BRAIN_PID=$(launchctl list | awk '$3 == "com.jarvis.alpha.brain" {print $1}' | head -1)
  [ "$BRAIN_PID" = "-" ] && BRAIN_PID=0
  emit ok restart node="$NODE_SHORT" service="alpha-brain" pid="${BRAIN_PID:-0}" dur_ms=$(($(time_ms) - RESTART_START))

  HEALTH_START=$(time_ms)
  HEALTH_URL="https://jarvis-brain.tail40ed36.ts.net:8186/health"
  HEALTH_CODE=$(curl -sk -o /dev/null -w "%{http_code}" --max-time 5 "$HEALTH_URL" 2>/dev/null || echo "000")
  HEALTH_DUR=$(($(time_ms) - HEALTH_START))
  if curl -sk --max-time 5 "$HEALTH_URL" 2>/dev/null | grep -q '"status":"ok"'; then
    echo "✅ Alpha Brain healthy after restart"
    emit ok health node="$NODE_SHORT" url="$HEALTH_URL" http_code="$HEALTH_CODE" dur_ms="$HEALTH_DUR"
  else
    echo "⚠️  Alpha Brain health check failed — check logs"
    tail -5 "${REPO_DIR}/logs/alpha_brain_error.log" 2>/dev/null
    emit fail health node="$NODE_SHORT" url="$HEALTH_URL" http_code="$HEALTH_CODE" dur_ms="$HEALTH_DUR" error="health body missing status ok"
  fi

  echo ""
  echo "Restarting Buddy Agent..."
  BUDDY_START=$(time_ms)
  launchctl unload ~/Library/LaunchAgents/com.jarvis.alpha.buddy.plist 2>/dev/null
  sleep 1
  launchctl load ~/Library/LaunchAgents/com.jarvis.alpha.buddy.plist
  sleep 1
  BUDDY_PID=$(launchctl list | awk '$3 == "com.jarvis.alpha.buddy" {print $1}' | head -1)
  [ "$BUDDY_PID" = "-" ] && BUDDY_PID=0
  echo "✅ Buddy agent restarted"
  emit ok restart node="$NODE_SHORT" service="alpha-buddy" pid="${BUDDY_PID:-0}" dur_ms=$(($(time_ms) - BUDDY_START))

  echo ""
  echo "── TEST GATE ────────────────────────────────────────────"
  VENV_PY="${REPO_DIR}/.venv/bin/python"
  if [ ! -x "$VENV_PY" ]; then
    echo "⚠️  No venv at $VENV_PY — skipping tests"
  elif [ ! -d "${REPO_DIR}/tests" ]; then
    echo "ℹ️  No tests/ directory — skipping"
  else
    cd "$REPO_DIR"
    PYTEST_LOG=$(mktemp)
    TEST_START=$(time_ms)
    if "$VENV_PY" -m pytest tests/ -q --tb=short --no-header >"$PYTEST_LOG" 2>&1; then
      PASS_LINE=$(grep -E "[0-9]+ passed" "$PYTEST_LOG" | tail -1)
      TEST_PASSED=$(echo "$PASS_LINE" | grep -oE "[0-9]+ passed" | grep -oE "[0-9]+" | head -1)
      echo "✅ Tests passed — $PASS_LINE"
      rm -f "$PYTEST_LOG"
      emit ok tests node="$NODE_SHORT" passed="${TEST_PASSED:-0}" failed=0 dur_ms=$(($(time_ms) - TEST_START))
    else
      TEST_ERR=$(tail -10 "$PYTEST_LOG" | tr '\n' ' ' | cut -c1-300)
      emit fail tests node="$NODE_SHORT" dur_ms=$(($(time_ms) - TEST_START)) error="$TEST_ERR"
      echo "❌ TESTS FAILED — details:"
      echo "─────────────────────────────────────────────────────────"
      cat "$PYTEST_LOG"
      echo "─────────────────────────────────────────────────────────"
      rm -f "$PYTEST_LOG"
      echo ""
      echo "⚠️  Services ARE running ($NEW_HEAD deployed). Tests flagged issues."
      echo "   Fix tests before next deploy or revert commit."
      exit 1
    fi
  fi
  echo "─────────────────────────────────────────────────────────"
fi

# ── Gateway branch (TD-88) ────────────────────────────────
if [ "$(hostname -s)" = "jarvis-gateway" ]; then
  GATEWAY_PLIST="${HOME}/Library/LaunchAgents/com.jarvis.alpha.gateway.plist"
  if [ -f "$GATEWAY_PLIST" ]; then
    echo ""
    echo "Restarting Alpha Gateway LaunchAgent..."

    PYCACHE_START=$(time_ms)
    launchctl unload "$GATEWAY_PLIST" 2>/dev/null || true
    sleep 1
    lsof -ti :8283 | xargs kill -9 2>/dev/null || true
    sleep 2
    find "${REPO_DIR}/gateway" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
    emit ok pycache node="$NODE_SHORT" dur_ms=$(($(time_ms) - PYCACHE_START))

    RESTART_START=$(time_ms)
    launchctl load "$GATEWAY_PLIST"
    sleep 4
    GW_PID=$(launchctl list | awk '$3 == "com.jarvis.alpha.gateway" {print $1}' | head -1)
    [ "$GW_PID" = "-" ] && GW_PID=0
    emit ok restart node="$NODE_SHORT" service="alpha-gateway" pid="${GW_PID:-0}" dur_ms=$(($(time_ms) - RESTART_START))

    HEALTH_START=$(time_ms)
    HEALTH_URL="https://127.0.0.1:8283/health"
    HEALTH_CODE=$(curl -sk -o /dev/null -w "%{http_code}" --max-time 5 "$HEALTH_URL" 2>/dev/null || echo "000")
    HEALTH_DUR=$(($(time_ms) - HEALTH_START))
    if curl -sk --max-time 5 "$HEALTH_URL" 2>/dev/null | grep -q '"status"'; then
      echo "✅ Alpha Gateway healthy after restart"
      emit ok health node="$NODE_SHORT" url="$HEALTH_URL" http_code="$HEALTH_CODE" dur_ms="$HEALTH_DUR"
    else
      echo "⚠️  Alpha Gateway health check failed — check logs"
      tail -5 "${REPO_DIR}/logs/alpha_gateway_error.log" 2>/dev/null
      emit fail health node="$NODE_SHORT" url="$HEALTH_URL" http_code="$HEALTH_CODE" dur_ms="$HEALTH_DUR" error="health body missing status"
      exit 1
    fi
  else
    echo "ℹ️  No Gateway LaunchAgent plist at $GATEWAY_PLIST — skipping restart"
  fi
fi

# ── Endpoint branch (TD-88) ───────────────────────────────
if [ "$(hostname -s)" = "jarvis-endpoint" ]; then
  DIST_START=$(time_ms)
  if [ ! -d "${REPO_DIR}/ui/dist" ]; then
    echo "⚠️  ui/dist missing on Endpoint — SCP from Air may have failed"
    echo "   Expected: ${REPO_DIR}/ui/dist/ with assets/ and index.html"
    emit fail dist_check node="$NODE_SHORT" dur_ms=$(($(time_ms) - DIST_START)) error="ui/dist directory missing"
    exit 1
  fi
  DIST_FILES=$(find "${REPO_DIR}/ui/dist" -type f | wc -l | tr -d ' ')
  echo "✅ ui/dist present — ${DIST_FILES} files"
  emit ok dist_check node="$NODE_SHORT" file_count="$DIST_FILES" dur_ms=$(($(time_ms) - DIST_START))
  echo "ℹ️  nginx reload deferred — run scripts/deploy_nginx_endpoint.sh if alpha.conf changed"
fi

# ── Final complete event ──
emit ok complete node="$NODE_SHORT" total_dur_ms=$(($(time_ms) - DEPLOY_START_MS))
