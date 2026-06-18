#!/bin/bash
set -uo pipefail

REPO_DIR="${JARVIS_ALPHA_REPO_DIR:-${HOME}/jarvis-alpha}"

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
    # TD-188: quote-by-key not quote-by-value-shape.
    # Hex commit hashes like 0855889 match ^[0-9]+$ but aren't valid JSON numbers
    # (leading zero). Whitelist actual numeric keys instead.
    case "$k" in
      file_count|dur_ms|exit_code|cost_usd|count|size_bytes|line_count)
        fields+=",\"$k\":$v"
        ;;
      *)
        # Escape quotes in string values
        v="${v//\"/\\\"}"
        fields+=",\"$k\":\"$v\""
        ;;
    esac
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

if [ -f "$SECRETS_FILE" ]; then
  set -a
  source "$SECRETS_FILE"
  set +a
else
  echo "⚠️  secrets file not found at $SECRETS_FILE"
  echo "   Existing clones will use native git auth; first-time clone still requires GITHUB_TOKEN."
fi

if [ ! -d "$REPO_DIR" ]; then
  if [ -z "${GITHUB_TOKEN:-}" ]; then
    echo "ERROR: GITHUB_TOKEN not set; cannot clone jarvis-alpha for first time"
    exit 1
  fi
  echo "Cloning jarvis-alpha for first time..."
  if ! git clone https://kphaas:${GITHUB_TOKEN}@github.com/kphaas/jarvis-alpha.git "$REPO_DIR"; then
    echo ""
    echo "❌ GIT CLONE FAILED — aborting."
    exit 1
  fi
  PULL_DUR=0
else
  cd "$REPO_DIR"
  PREV_HEAD=$(git rev-parse --short HEAD 2>/dev/null || echo "")
  if [ -n "${GITHUB_TOKEN:-}" ]; then
    git config credential.helper ""
    GIT_TERMINAL_PROMPT=0 git remote set-url origin https://kphaas:${GITHUB_TOKEN}@github.com/kphaas/jarvis-alpha.git
  else
    echo "ℹ️  GITHUB_TOKEN not set; using existing git remote/native auth"
  fi

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
NEW_HEAD_FULL=$(git -C "$REPO_DIR" rev-parse HEAD)

if [ -f "${REPO_DIR}/scripts/lib/node_addresses.sh" ]; then
  source "${REPO_DIR}/scripts/lib/node_addresses.sh"
fi
if [ -f "${REPO_DIR}/scripts/lib/restart_markers.sh" ]; then
  source "${REPO_DIR}/scripts/lib/restart_markers.sh"
else
  echo "ERROR: restart marker helper missing"
  exit 1
fi

# Capture changed files list AND count (TD-107: used for restart classification)
if [ -n "${PREV_HEAD:-}" ] && [ "$PREV_HEAD" != "$NEW_HEAD" ]; then
  CHANGED_FILES=$(git -C "$REPO_DIR" diff --name-only "${PREV_HEAD}..${NEW_HEAD}")
  FILE_COUNT=$(echo "$CHANGED_FILES" | wc -l | tr -d ' ')
else
  CHANGED_FILES=""
  FILE_COUNT=0
fi

# ── TD-107: Per-node restart classifier ──
# Conservative default: RESTART (fail-safe). Only skip when sure nothing runtime-relevant.
# Rules match existing commit-script classifier + node-specific paths.
DEPLOY_STATE_DIR="${JARVIS_ALPHA_DEPLOY_STATE_DIR:-${HOME}/.jarvis-alpha-deploy}"

changed_files_for_service() {
  local service="$1"
  local marker_head
  marker_head=$(restart_marker_read "$DEPLOY_STATE_DIR" "$service")
  restart_marker_changed_files "$REPO_DIR" "$marker_head" "$NEW_HEAD_FULL" "$CHANGED_FILES"
}

service_has_changes_matching() {
  local service="$1"
  local pattern="$2"
  local service_changed_files
  service_changed_files=$(changed_files_for_service "$service")
  [ -n "$service_changed_files" ] && echo "$service_changed_files" | grep -qE "$pattern"
}

mark_service_checked() {
  local service="$1"
  restart_marker_write "$DEPLOY_STATE_DIR" "$service" "$NEW_HEAD_FULL"
}

needs_restart_brain() {
  service_has_changes_matching "alpha-brain" '(^brain/|^common/|^db/|^scripts/apply_migrations\.sh|\.py$|^scripts/start_alpha_brain\.sh$|^launchagents/com\.jarvis\.alpha\.(brain|buddy)\.plist$)'
}

needs_reload_school_email() {
  service_has_changes_matching "alpha-school-email" '(^launchagents/com\.jarvis\.alpha\.(school-email|gmail-health|at0-mail|at0-mail-health)\.template\.plist$|^scripts/start_alpha_(school_email|gmail_health|at0_mail|at0_mail_health)\.sh$|^scripts/install_launchagents\.py$)'
}

needs_reload_sweep_cert() {
  service_has_changes_matching "alpha-sweep-cert-renewal" "(^launchagents/com\\.jarvis\\.alpha\\.sweep-cert-renewal\\.${NODE_SHORT}\\.template\\.plist$|^launchagents/com\\.jarvis\\.alpha\\.sweep-cert-renewal\\.template\\.plist$|^scripts/install_launchagents\\.py$)"
}

needs_restart_temporal_worker() {
  service_has_changes_matching "alpha-temporal-worker" '(^brain/dream/|^brain/services/(planner|reviewer)\.py$|^scripts/start_temporal_worker\.sh$|^launchagents/com\.jarvis\.alpha\.temporal\.worker(\.template)?\.plist$)'
}

needs_restart_gateway() {
  service_has_changes_matching "alpha-gateway" '(^gateway/|^common/|\.py$|^scripts/start_alpha_gateway\.sh$|^launchagents/com\.jarvis\.alpha\.gateway\.plist$)'
}

needs_restart_endpoint() {
  service_has_changes_matching "alpha-endpoint" '(^endpoint/|^ui/dist/|^scripts/deploy_nginx_endpoint\.sh$)'
}

needs_restart_at0_voice() {
  service_has_changes_matching "alpha-at0-voice" '(^endpoint/voice/|^launchagents/com\.jarvis\.alpha\.at0-voice\.endpoint\.template\.plist$)'
}

needs_restart_watchdog() {
  service_has_changes_matching "alpha-watchdog" '(^brain/agents/watchdog_agent\.py$|^scripts/start_alpha_watchdog\.sh$|^launchagents/com\.jarvis\.alpha\.watchdog\.plist$)'
}

needs_restart_observability() {
  service_has_changes_matching "alpha-observability" '(^config/observability/brain/|^launchagents/com\.jarvis\.alpha\.(fluentbit|loki)\.plist$)'
}

sync_brain_observability_configs() {
  local sync_start
  sync_start=$(time_ms)
  local fluent_src="${REPO_DIR}/config/observability/brain/fluent-bit.yaml"
  local loki_src="${REPO_DIR}/config/observability/brain/loki-config.yaml"
  local loki_host="${JARVIS_ALPHA_LOKI_HOST:-127.0.0.1}"
  local loki_http_listen_address="${JARVIS_ALPHA_LOKI_HTTP_LISTEN_ADDRESS:-0.0.0.0}"
  local loki_grpc_listen_address="${JARVIS_ALPHA_LOKI_GRPC_LISTEN_ADDRESS:-127.0.0.1}"
  local loki_instance_addr="${JARVIS_ALPHA_LOKI_INSTANCE_ADDR:-127.0.0.1}"

  mkdir -p "${HOME}/fluent-bit/db" "${HOME}/jarvis/loki"

  if [ -f "$fluent_src" ]; then
    sed \
      -e "s|{{HOME}}|${HOME}|g" \
      -e "s|{{REPO_DIR}}|${REPO_DIR}|g" \
      -e "s|{{LOKI_HOST}}|${loki_host}|g" \
      "$fluent_src" > "${HOME}/fluent-bit/fluent-bit.yaml"
  fi
  if [ -f "$loki_src" ]; then
    sed \
      -e "s|{{HOME}}|${HOME}|g" \
      -e "s|{{LOKI_HTTP_LISTEN_ADDRESS}}|${loki_http_listen_address}|g" \
      -e "s|{{LOKI_GRPC_LISTEN_ADDRESS}}|${loki_grpc_listen_address}|g" \
      -e "s|{{LOKI_INSTANCE_ADDR}}|${loki_instance_addr}|g" \
      "$loki_src" > "${HOME}/jarvis/loki/loki-config.yaml"
  fi

  emit ok config_sync node="$NODE_SHORT" service="observability" dur_ms=$(($(time_ms) - sync_start))
}

restart_launchagent() {
  local display_service="$1"
  local label="$2"
  local plist="$3"
  local restart_start
  restart_start=$(time_ms)

  if [ ! -f "$plist" ]; then
    emit fail restart node="$NODE_SHORT" service="$display_service" dur_ms=$(($(time_ms) - restart_start)) error="plist missing"
    echo "❌ LaunchAgent plist missing for $display_service: $plist"
    exit 1
  fi

  launchctl unload "$plist" 2>/dev/null || true
  sleep 1
  if ! launchctl load "$plist"; then
    emit fail restart node="$NODE_SHORT" service="$display_service" dur_ms=$(($(time_ms) - restart_start)) error="launchctl load failed"
    echo "❌ LaunchAgent load failed for $display_service"
    exit 1
  fi
  sleep 1

  local pid
  pid=$(launchctl list | awk -v label="$label" '$3 == label {print $1}' | head -1)
  [ "$pid" = "-" ] && pid=0
  emit ok restart node="$NODE_SHORT" service="$display_service" pid="${pid:-0}" dur_ms=$(($(time_ms) - restart_start))
}

emit ok pull node="$NODE_SHORT" from_hash="${PREV_HEAD:-none}" to_hash="$NEW_HEAD" file_count="$FILE_COUNT" dur_ms="$PULL_DUR"

if [ "$NODE_SHORT" = "brain" ]; then
  echo ""
  echo "Syncing Spark personality vault..."
  PERSONA_START=$(time_ms)
  PERSONA_LOG=$(mktemp)
  if bash "${REPO_DIR}/scripts/sync_personality_vault.sh" >"$PERSONA_LOG" 2>&1; then
    PERSONA_HEAD=$(grep -oE 'head=[A-Za-z0-9]+' "$PERSONA_LOG" | tail -1 | cut -d= -f2)
    cat "$PERSONA_LOG"
    rm -f "$PERSONA_LOG"
    emit ok personality_sync node="$NODE_SHORT" service="spark-personality" head="${PERSONA_HEAD:-unknown}" dur_ms=$(($(time_ms) - PERSONA_START))
  else
    PERSONA_ERR=$(tail -5 "$PERSONA_LOG" | tr '\n' ' ' | cut -c1-300)
    cat "$PERSONA_LOG" >&2
    rm -f "$PERSONA_LOG"
    emit fail personality_sync node="$NODE_SHORT" service="spark-personality" dur_ms=$(($(time_ms) - PERSONA_START)) error="$PERSONA_ERR"
    echo "❌ Spark personality vault sync failed — aborting pull deploy."
    echo "   Check: cd ~/jarvis-personality && git status"
    exit 1
  fi
fi

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
if [ "$NODE_SHORT" = "brain" ]; then
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
if [ "$NODE_SHORT" = "brain" ] && ! needs_restart_brain; then
  echo "ℹ️  Skipping Brain restart — no runtime-relevant files changed (TD-107)"
  emit skip restart node="$NODE_SHORT" service="alpha-brain" reason="no_runtime_changes"
  emit skip restart node="$NODE_SHORT" service="alpha-buddy" reason="no_runtime_changes"
  emit skip tests node="$NODE_SHORT" reason="no_runtime_changes"
  mark_service_checked "alpha-brain"
  mark_service_checked "alpha-buddy"
elif [ -f "$BRAIN_PLIST" ]; then
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
  HEALTH_URL="${JARVIS_ALPHA_BRAIN_HEALTH_URL:-https://localhost:8186/health}"
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
  mark_service_checked "alpha-brain"
  mark_service_checked "alpha-buddy"
  echo "─────────────────────────────────────────────────────────"
fi

WATCHDOG_PLIST="${HOME}/Library/LaunchAgents/com.jarvis.alpha.watchdog.plist"
if [ "$NODE_SHORT" = "brain" ] && needs_restart_watchdog; then
  echo ""
  echo "Restarting Watchdog Agent..."
  restart_launchagent "alpha-watchdog" "com.jarvis.alpha.watchdog" "$WATCHDOG_PLIST"
  mark_service_checked "alpha-watchdog"
elif [ "$NODE_SHORT" = "brain" ]; then
  emit skip restart node="$NODE_SHORT" service="alpha-watchdog" reason="no_watchdog_changes"
  mark_service_checked "alpha-watchdog"
fi

if [ "$NODE_SHORT" = "brain" ] && needs_restart_observability; then
  echo ""
  echo "Syncing observability configs..."
  sync_brain_observability_configs

  echo "Restarting Alpha observability LaunchAgents..."
  restart_launchagent "alpha-fluentbit" "com.jarvis.alpha.fluentbit" "${HOME}/Library/LaunchAgents/com.jarvis.alpha.fluentbit.plist"
  restart_launchagent "alpha-loki" "com.jarvis.alpha.loki" "${HOME}/Library/LaunchAgents/com.jarvis.alpha.loki.plist"
  mark_service_checked "alpha-observability"
elif [ "$NODE_SHORT" = "brain" ]; then
  emit skip restart node="$NODE_SHORT" service="alpha-fluentbit" reason="no_observability_changes"
  emit skip restart node="$NODE_SHORT" service="alpha-loki" reason="no_observability_changes"
  mark_service_checked "alpha-observability"
fi

TEMPORAL_WORKER_PLIST="${HOME}/Library/LaunchAgents/com.jarvis.alpha.temporal.worker.plist"
if [ "$NODE_SHORT" = "brain" ] && needs_restart_temporal_worker; then
  echo ""
  echo "Restarting Alpha Temporal Worker..."
  TEMPORAL_START=$(time_ms)
  if [ ! -f "$TEMPORAL_WORKER_PLIST" ]; then
    emit fail restart node="$NODE_SHORT" service="alpha-temporal-worker" dur_ms=$(($(time_ms) - TEMPORAL_START)) error="plist missing"
    echo "❌ Temporal worker LaunchAgent plist missing"
    exit 1
  fi
  find "${REPO_DIR}/brain/dream" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
  launchctl unload "$TEMPORAL_WORKER_PLIST" 2>/dev/null || true
  sleep 1
  launchctl load "$TEMPORAL_WORKER_PLIST"
  sleep 2
  TEMPORAL_PID=$(launchctl list | awk '$3 == "com.jarvis.alpha.temporal.worker" {print $1}' | head -1)
  [ "$TEMPORAL_PID" = "-" ] && TEMPORAL_PID=0
  echo "✅ Temporal worker restarted"
  emit ok restart node="$NODE_SHORT" service="alpha-temporal-worker" pid="${TEMPORAL_PID:-0}" dur_ms=$(($(time_ms) - TEMPORAL_START))
  mark_service_checked "alpha-temporal-worker"
elif [ "$NODE_SHORT" = "brain" ]; then
  emit skip restart node="$NODE_SHORT" service="alpha-temporal-worker" reason="no_worker_changes"
  mark_service_checked "alpha-temporal-worker"
fi

SCHOOL_EMAIL_PLIST="${HOME}/Library/LaunchAgents/com.jarvis.alpha.school-email.plist"
GMAIL_HEALTH_PLIST="${HOME}/Library/LaunchAgents/com.jarvis.alpha.gmail-health.plist"
AT0_MAIL_PLIST="${HOME}/Library/LaunchAgents/com.jarvis.alpha.at0-mail.plist"
AT0_MAIL_HEALTH_PLIST="${HOME}/Library/LaunchAgents/com.jarvis.alpha.at0-mail-health.plist"
if [ "$NODE_SHORT" = "brain" ] && needs_reload_school_email; then
  echo ""
  echo "Refreshing Alpha School Email LaunchAgent..."
  SCHOOL_START=$(time_ms)
  INSTALL_LOG=$(mktemp)
  if ! python3 "${REPO_DIR}/scripts/install_launchagents.py" --node brain >"$INSTALL_LOG" 2>&1; then
    SCHOOL_DUR=$(($(time_ms) - SCHOOL_START))
    INSTALL_ERR=$(tail -5 "$INSTALL_LOG" | tr '\n' ' ' | cut -c1-300)
    rm -f "$INSTALL_LOG"
    emit fail restart node="$NODE_SHORT" service="alpha-school-email" dur_ms="$SCHOOL_DUR" error="$INSTALL_ERR"
    echo "❌ School email LaunchAgent install failed"
    exit 1
  fi
  rm -f "$INSTALL_LOG"
  if [ -f "$SCHOOL_EMAIL_PLIST" ]; then
    launchctl unload "$SCHOOL_EMAIL_PLIST" 2>/dev/null || true
    launchctl load "$SCHOOL_EMAIL_PLIST"
    SCHOOL_PID=$(launchctl list | awk '$3 == "com.jarvis.alpha.school-email" {print $1}' | head -1)
    [ "$SCHOOL_PID" = "-" ] && SCHOOL_PID=0
    echo "✅ School email LaunchAgent refreshed"
    emit ok restart node="$NODE_SHORT" service="alpha-school-email" pid="${SCHOOL_PID:-0}" dur_ms=$(($(time_ms) - SCHOOL_START))
  else
    emit fail restart node="$NODE_SHORT" service="alpha-school-email" dur_ms=$(($(time_ms) - SCHOOL_START)) error="plist missing after install"
    echo "❌ School email LaunchAgent plist missing after install"
    exit 1
  fi
  if [ -f "$GMAIL_HEALTH_PLIST" ]; then
    launchctl unload "$GMAIL_HEALTH_PLIST" 2>/dev/null || true
    launchctl load "$GMAIL_HEALTH_PLIST"
    GMAIL_HEALTH_PID=$(launchctl list | awk '$3 == "com.jarvis.alpha.gmail-health" {print $1}' | head -1)
    [ "$GMAIL_HEALTH_PID" = "-" ] && GMAIL_HEALTH_PID=0
    echo "✅ Gmail health LaunchAgent refreshed"
    emit ok restart node="$NODE_SHORT" service="alpha-gmail-health" pid="${GMAIL_HEALTH_PID:-0}" dur_ms=$(($(time_ms) - SCHOOL_START))
  else
    emit fail restart node="$NODE_SHORT" service="alpha-gmail-health" dur_ms=$(($(time_ms) - SCHOOL_START)) error="plist missing after install"
    echo "❌ Gmail health LaunchAgent plist missing after install"
    exit 1
  fi
  if [ -f "$AT0_MAIL_PLIST" ]; then
    launchctl unload "$AT0_MAIL_PLIST" 2>/dev/null || true
    launchctl load "$AT0_MAIL_PLIST"
    AT0_MAIL_PID=$(launchctl list | awk '$3 == "com.jarvis.alpha.at0-mail" {print $1}' | head -1)
    [ "$AT0_MAIL_PID" = "-" ] && AT0_MAIL_PID=0
    echo "✅ AT-0 Herald mail LaunchAgent refreshed"
    emit ok restart node="$NODE_SHORT" service="alpha-at0-mail" pid="${AT0_MAIL_PID:-0}" dur_ms=$(($(time_ms) - SCHOOL_START))
  else
    emit fail restart node="$NODE_SHORT" service="alpha-at0-mail" dur_ms=$(($(time_ms) - SCHOOL_START)) error="plist missing after install"
    echo "❌ AT-0 Herald mail LaunchAgent plist missing after install"
    exit 1
  fi
  if [ -f "$AT0_MAIL_HEALTH_PLIST" ]; then
    launchctl unload "$AT0_MAIL_HEALTH_PLIST" 2>/dev/null || true
    launchctl load "$AT0_MAIL_HEALTH_PLIST"
    AT0_MAIL_HEALTH_PID=$(launchctl list | awk '$3 == "com.jarvis.alpha.at0-mail-health" {print $1}' | head -1)
    [ "$AT0_MAIL_HEALTH_PID" = "-" ] && AT0_MAIL_HEALTH_PID=0
    echo "✅ AT-0 Herald mail health LaunchAgent refreshed"
    emit ok restart node="$NODE_SHORT" service="alpha-at0-mail-health" pid="${AT0_MAIL_HEALTH_PID:-0}" dur_ms=$(($(time_ms) - SCHOOL_START))
  else
    emit fail restart node="$NODE_SHORT" service="alpha-at0-mail-health" dur_ms=$(($(time_ms) - SCHOOL_START)) error="plist missing after install"
    echo "❌ AT-0 Herald mail health LaunchAgent plist missing after install"
    exit 1
  fi
  mark_service_checked "alpha-school-email"
elif [ "$NODE_SHORT" = "brain" ]; then
  emit skip restart node="$NODE_SHORT" service="alpha-school-email" reason="no_launchagent_changes"
  mark_service_checked "alpha-school-email"
fi

SWEEP_CERT_LABEL="com.jarvis.alpha.sweep-cert-renewal.${NODE_SHORT}"
SWEEP_CERT_PLIST="${HOME}/Library/LaunchAgents/${SWEEP_CERT_LABEL}.plist"
OLD_SWEEP_CERT_PLIST="${HOME}/Library/LaunchAgents/com.jarvis.alpha.sweep-cert-renewal.plist"
if needs_reload_sweep_cert; then
  echo ""
  echo "Refreshing Sweep cert renewal LaunchAgent..."
  SWEEP_START=$(time_ms)
  INSTALL_LOG=$(mktemp)
  if ! python3 "${REPO_DIR}/scripts/install_launchagents.py" --node "$NODE_SHORT" >"$INSTALL_LOG" 2>&1; then
    SWEEP_DUR=$(($(time_ms) - SWEEP_START))
    INSTALL_ERR=$(tail -5 "$INSTALL_LOG" | tr '\n' ' ' | cut -c1-300)
    rm -f "$INSTALL_LOG"
    emit fail restart node="$NODE_SHORT" service="alpha-sweep-cert-renewal" dur_ms="$SWEEP_DUR" error="$INSTALL_ERR"
    echo "❌ Sweep cert renewal LaunchAgent install failed"
    exit 1
  fi
  rm -f "$INSTALL_LOG"
  if [ -f "$OLD_SWEEP_CERT_PLIST" ]; then
    launchctl unload "$OLD_SWEEP_CERT_PLIST" 2>/dev/null || true
    rm -f "$OLD_SWEEP_CERT_PLIST"
  fi
  if [ -f "$SWEEP_CERT_PLIST" ]; then
    launchctl unload "$SWEEP_CERT_PLIST" 2>/dev/null || true
    launchctl load "$SWEEP_CERT_PLIST"
    SWEEP_CERT_PID=$(launchctl list | awk -v label="$SWEEP_CERT_LABEL" '$3 == label {print $1}' | head -1)
    [ "$SWEEP_CERT_PID" = "-" ] && SWEEP_CERT_PID=0
    echo "✅ Sweep cert renewal LaunchAgent refreshed"
    emit ok restart node="$NODE_SHORT" service="alpha-sweep-cert-renewal" pid="${SWEEP_CERT_PID:-0}" dur_ms=$(($(time_ms) - SWEEP_START))
  else
    emit fail restart node="$NODE_SHORT" service="alpha-sweep-cert-renewal" dur_ms=$(($(time_ms) - SWEEP_START)) error="plist missing after install"
    echo "❌ Sweep cert renewal LaunchAgent plist missing after install"
    exit 1
  fi
  mark_service_checked "alpha-sweep-cert-renewal"
elif [ "$NODE_SHORT" = "brain" ]; then
  emit skip restart node="$NODE_SHORT" service="alpha-sweep-cert-renewal" reason="no_launchagent_changes"
  mark_service_checked "alpha-sweep-cert-renewal"
fi

# ── Gateway branch (TD-88) ────────────────────────────────
if [ "$NODE_SHORT" = "gateway" ]; then
  GATEWAY_PLIST="${HOME}/Library/LaunchAgents/com.jarvis.alpha.gateway.plist"
  if ! needs_restart_gateway; then
    echo "ℹ️  Skipping Gateway restart — no runtime-relevant files changed (TD-107)"
    emit skip restart node="$NODE_SHORT" service="alpha-gateway" reason="no_runtime_changes"
    mark_service_checked "alpha-gateway"
  elif [ -f "$GATEWAY_PLIST" ]; then
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
    mark_service_checked "alpha-gateway"
  else
    echo "ℹ️  No Gateway LaunchAgent plist at $GATEWAY_PLIST — skipping restart"
  fi
fi

# ── Endpoint branch (TD-88) ───────────────────────────────
if [ "$NODE_SHORT" = "endpoint" ]; then
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

  AT0_VOICE_PLIST_SOURCE="${REPO_DIR}/launchagents/com.jarvis.alpha.at0-voice.endpoint.template.plist"
  AT0_VOICE_PLIST_TARGET="${HOME}/Library/LaunchAgents/com.jarvis.alpha.at0-voice.endpoint.plist"
  if needs_restart_at0_voice; then
    echo ""
    echo "Installing AT-0 voice worker..."
    AT0_INSTALL_START=$(time_ms)
    if ! bash "${REPO_DIR}/endpoint/voice/bin/install_at0_voice_runtime.sh"; then
      emit fail restart node="$NODE_SHORT" service="alpha-at0-voice" dur_ms=$(($(time_ms) - AT0_INSTALL_START)) error="install failed"
      echo "❌ AT-0 voice worker install failed"
      exit 1
    fi
    cp "$AT0_VOICE_PLIST_SOURCE" "$AT0_VOICE_PLIST_TARGET"

    echo "Restarting AT-0 voice worker..."
    launchctl unload "$AT0_VOICE_PLIST_TARGET" 2>/dev/null || true
    sleep 1
    if ! launchctl load "$AT0_VOICE_PLIST_TARGET"; then
      emit fail restart node="$NODE_SHORT" service="alpha-at0-voice" dur_ms=$(($(time_ms) - AT0_INSTALL_START)) error="launchctl load failed"
      echo "❌ AT-0 voice worker LaunchAgent load failed"
      exit 1
    fi
    sleep 2
    AT0_VOICE_PID=$(launchctl list | awk '$3 == "com.jarvis.alpha.at0-voice" {print $1}' | head -1)
    [ "$AT0_VOICE_PID" = "-" ] && AT0_VOICE_PID=0
    emit ok restart node="$NODE_SHORT" service="alpha-at0-voice" pid="${AT0_VOICE_PID:-0}" dur_ms=$(($(time_ms) - AT0_INSTALL_START))

    AT0_HEALTH_START=$(time_ms)
    AT0_HEALTH_URL="${JARVIS_AT0_VOICE_HEALTH_URL:-http://127.0.0.1:4212/health}"
    AT0_HEALTH_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$AT0_HEALTH_URL" 2>/dev/null || echo "000")
    if [ "$AT0_HEALTH_CODE" = "200" ]; then
      echo "✅ AT-0 voice worker reachable"
      emit ok health node="$NODE_SHORT" service="alpha-at0-voice" url="$AT0_HEALTH_URL" http_code="$AT0_HEALTH_CODE" dur_ms=$(($(time_ms) - AT0_HEALTH_START))
    else
      echo "⚠️  AT-0 voice worker health returned HTTP $AT0_HEALTH_CODE"
      emit fail health node="$NODE_SHORT" service="alpha-at0-voice" url="$AT0_HEALTH_URL" http_code="$AT0_HEALTH_CODE" dur_ms=$(($(time_ms) - AT0_HEALTH_START)) error="health not reachable"
      exit 1
    fi
    mark_service_checked "alpha-at0-voice"
  else
    emit skip restart node="$NODE_SHORT" service="alpha-at0-voice" reason="no_runtime_changes"
    mark_service_checked "alpha-at0-voice"
  fi
fi

# ── Final complete event ──
emit ok complete node="$NODE_SHORT" total_dur_ms=$(($(time_ms) - DEPLOY_START_MS))
