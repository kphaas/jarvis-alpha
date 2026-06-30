#!/bin/bash
# jarvisalpha_deploy.sh — Fan-out deploy for jarvis-alpha (post-merge).
#
# Run after a PR merges into main. Refuses unless on main + clean tree + HEAD
# matches origin/main after `git pull --ff-only`. Then fans out to all nodes:
# Sandbox auto-pull → Endpoint UI dist scp → Brain → Gateway → Endpoint pulls.
#
# Brain → Gateway → Endpoint use the TD-107 self-classifying pull script;
# pull script decides whether to restart based on changed paths.
#
# Verbosity (additive, Ansible-style):
#   (default)   NORMAL — pretty event rendering via render_events.py
#   VERBOSE=1   -v      — raw human output from pull script visible alongside events
#   VERBOSE=2   -vv     — -v + raw ##EVT## JSON visible
#
# Env:
#   JARVIS_SKIP_SANDBOX=1   Skip Sandbox auto-pull (e.g. when run from Sandbox)
#
# Full log always written to /tmp/jarvisalpha_deploy_YYYYMMDD_HHMMSS.log

set -uo pipefail

# ── Args ──────────────────────────────────────────────────
case "${1:-}" in
  -h|--help)
    sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
    ;;
esac

# ── Config ────────────────────────────────────────────────
REPO_DIR="${JARVIS_ALPHA_REPO_DIR:-${HOME}/jarvis-alpha}"
source "${REPO_DIR}/scripts/lib/node_addresses.sh"

BRAIN="${JARVIS_ALPHA_BRAIN_SSH}"
GATEWAY="${JARVIS_ALPHA_GATEWAY_SSH}"
ENDPOINT="${JARVIS_ALPHA_ENDPOINT_SSH}"
SANDBOX="${JARVIS_ALPHA_SANDBOX_SSH}"
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no)
if [[ -n "${JARVIS_ALPHA_SSH_KEY:-}" ]]; then
  SSH_OPTS=(-i "$JARVIS_ALPHA_SSH_KEY" -o IdentitiesOnly=yes "${SSH_OPTS[@]}")
fi
RENDERER="${REPO_DIR}/scripts/render_events.py"
VERBOSE="${VERBOSE:-0}"

# ── Log file ──────────────────────────────────────────────
LOG_TS=$(date +%Y%m%d_%H%M%S)
LOG_FILE="${LOG:-/tmp/jarvisalpha_deploy_${LOG_TS}.log}"
exec > >(tee -a "$LOG_FILE") 2>&1

# ── Colors ────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
DIM='\033[2m'
BOLD='\033[1m'
RESET='\033[0m'

# ── Global state ──────────────────────────────────────────
DEPLOY_START=$SECONDS
DEPLOY_FAILED=0

# ── Helpers (lifted verbatim from jarvisalpha_commit.sh) ──
phase_header() {
  local label="$1"
  printf '\n%b── %s %s%b\n' "$CYAN" "$label" "─────────────────────────────────────────────────────" "$RESET"
}

done_banner() {
  local hash="$1"
  local dur="$2"
  printf '\n%b══ DONE %s%b\n' "$BOLD$GREEN" "═════════════════════════════════════════════════════" "$RESET"
  printf '  ALPHA %b✅%b %s deployed in %ds\n' "$GREEN" "$RESET" "$hash" "$dur"
  printf '\n'
  printf '  Log:   %s\n' "$LOG_FILE"
  printf '  Undo:  PR a revert of %s, then re-run this script after merge\n' "$hash"
  printf '\n'
}

step_ok() {
  local step="$1"
  local detail="$2"
  local dur="${3:-}"
  printf '  %b✅%b %-22s %-45s %s\n' "$GREEN" "$RESET" "$step" "$detail" "$dur"
}

step_fail() {
  local step="$1"
  local detail="$2"
  printf '  %b❌%b %-22s %s\n' "$RED" "$RESET" "$step" "$detail" >&2
}

lc() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

fmt_s() {
  awk -v s="$1" 'BEGIN { if (s < 10) printf "%.1fs", s; else printf "%ds", s }'
}

failure_box() {
  local node_label="$1"
  local node_host="$2"
  local fail_json="$3"

  local phase error http_code
  phase=$(echo "$fail_json" | python3 -c 'import json,sys; d=json.loads(sys.stdin.read()); print(d.get("phase","unknown"))')
  error=$(echo "$fail_json" | python3 -c 'import json,sys; d=json.loads(sys.stdin.read()); print(d.get("error","(no error text)"))')
  http_code=$(echo "$fail_json" | python3 -c 'import json,sys; d=json.loads(sys.stdin.read()); print(d.get("http_code",""))' 2>/dev/null)

  printf '\n%b╔════════════════════════════════════════════════════════╗%b\n' "$RED$BOLD" "$RESET" >&2
  printf '%b║ ❌ FAN-OUT HALTED — %s %s failed%b\n' "$RED$BOLD" "$node_label" "$phase" "$RESET" >&2
  printf '%b╠════════════════════════════════════════════════════════╣%b\n' "$RED$BOLD" "$RESET" >&2
  printf '  Node:    %s (%s)\n' "$node_label" "$node_host" >&2
  printf '  Phase:   %s\n' "$phase" >&2
  printf '  Error:   %s\n' "$error" >&2
  [ -n "$http_code" ] && [ "$http_code" != "0" ] && printf '  HTTP:    %s\n' "$http_code" >&2
  printf '\n' >&2

  printf '%b── DIAGNOSTICS ──%b\n' "$BOLD" "$RESET" >&2
  printf '\n  Last 20 lines of error log:\n' >&2

  local service_log
  case "$phase" in
    restart|health)
      case "$node_label" in
        Brain) service_log="alpha_brain_error.log" ;;
        Gateway) service_log="alpha_gateway_error.log" ;;
        *) service_log="alpha_$(lc "$node_label")_error.log" ;;
      esac
      ssh -o ConnectTimeout=10 "${SSH_OPTS[@]}" "$node_host" \
        "tail -20 ~/jarvis-alpha/logs/$service_log 2>/dev/null || echo '(log file not readable)'" 2>&1 \
        | sed 's/^/    /' >&2
      ;;
    tests)
      ssh -o ConnectTimeout=10 "${SSH_OPTS[@]}" "$node_host" \
        "tail -30 ~/jarvis-alpha/logs/alpha_brain_error.log 2>/dev/null | grep -iE 'error|traceback|assert' | head -15" 2>&1 \
        | sed 's/^/    /' >&2
      ;;
    migration|pull)
      ssh -o ConnectTimeout=10 "${SSH_OPTS[@]}" "$node_host" \
        "cd ~/jarvis-alpha && git log -1 --oneline && git status --short" 2>&1 \
        | sed 's/^/    /' >&2
      ;;
    *)
      printf '    (no diagnostics available for phase=%s)\n' "$phase" >&2
      ;;
  esac

  printf '\n  launchctl jarvis agents:\n' >&2
  ssh -o ConnectTimeout=10 "${SSH_OPTS[@]}" "$node_host" \
    "launchctl list | grep 'com.jarvis.alpha' || echo '(no matching agents)'" 2>&1 \
    | sed 's/^/    /' >&2

  printf '\n%b── RECOVERY ──%b\n' "$BOLD" "$RESET" >&2
  printf '  Investigate:  ssh %s "tail -50 ~/jarvis-alpha/logs/alpha_*_error.log"\n' "$(lc "$node_label")" >&2
  printf '  Retry pull:   ssh %s "bash ~/jarvis-alpha/scripts/jarvisalpha_pull.sh"\n' "$(lc "$node_label")" >&2
  printf '  Rollback:     ssh %s "cd ~/jarvis-alpha && git reset --hard HEAD~1 && bash scripts/jarvisalpha_pull.sh"\n' "$(lc "$node_label")" >&2
  printf '\n  Full log: %s\n' "$LOG_FILE" >&2
  printf '%b╚════════════════════════════════════════════════════════╝%b\n' "$RED$BOLD" "$RESET" >&2
}

remote_pull() {
  local node_label="$1"
  local node_host="$2"

  local start=$SECONDS
  local render_ec

  printf '\n  %s %s\n' "$node_label" "$(printf '%0.s.' $(seq 1 $((55 - ${#node_label}))))"

  local tmp_out
  tmp_out=$(mktemp)
  ssh "${SSH_OPTS[@]}" -o ServerAliveInterval=30 "$node_host" \
    "bash ~/jarvis-alpha/scripts/jarvisalpha_pull.sh" 2>&1 \
    | VERBOSE="$VERBOSE" python3 "$RENDERER" --node="$(lc "$node_label")" \
    > "$tmp_out"
  render_ec=$?

  grep -v '^##RENDER_DONE##\|^##RENDER_FAIL##' "$tmp_out"

  local dur=$((SECONDS - start))
  printf '  %s %s %s' "$node_label" "$(printf '%0.s.' $(seq 1 $((50 - ${#node_label}))))" "$(fmt_s $dur)"

  if [ $render_ec -eq 0 ]; then
    printf ' %b✅%b\n' "$GREEN" "$RESET"
    rm -f "$tmp_out"
    return 0
  else
    printf ' %b❌%b\n' "$RED" "$RESET"
    local fail_json
    fail_json=$(grep "^##RENDER_FAIL##" "$tmp_out" | head -1 | sed 's/^##RENDER_FAIL##//')
    rm -f "$tmp_out"
    DEPLOY_FAILED=1
    if [ -n "$fail_json" ]; then
      failure_box "$node_label" "$node_host" "$fail_json"
    else
      printf '\n%b❌ %s pull failed (no structured failure event)%b\n' "$RED" "$node_label" "$RESET" >&2
      printf '  See log: %s\n' "$LOG_FILE" >&2
    fi
    return 1
  fi
}

run_post_deploy_smokes() {
  phase_header "POST-DEPLOY SMOKE"

  local smoke_failed=0
  local settings_base_url="${JARVIS_ALPHA_BRAIN_HEALTH_URL%/health}"
  local settings_endpoint_url="${JARVIS_ALPHA_ENDPOINT_HEALTH_URL%/}/settings"

  if [[ "${JARVIS_SKIP_SETTINGS_SMOKE:-0}" == "1" || "${JARVIS_ALPHA_SKIP_SETTINGS_SMOKE:-0}" == "1" ]]; then
    printf '  %b⏭%b %-22s %-45s %s\n' "$YELLOW" "$RESET" "settings smoke" "SKIPPED (JARVIS_SKIP_SETTINGS_SMOKE=1)" ""
  else
    local smoke_start=$SECONDS
    local smoke_out
    local smoke_ec

    smoke_out=$(
      SETTINGS_SMOKE_BASE_URL="$settings_base_url" \
      SETTINGS_SMOKE_ENDPOINT_URL="$settings_endpoint_url" \
      SETTINGS_SMOKE_TOKEN_SSH_TARGET="$BRAIN" \
        python3 "$REPO_DIR/scripts/smoke_settings.py" 2>&1
    )
    smoke_ec=$?
    if [ $smoke_ec -ne 0 ]; then
      step_fail "settings smoke" "failed"
      echo "$smoke_out" >&2
      smoke_failed=1
    else
      local smoke_summary
      smoke_summary=$(printf '%s\n' "$smoke_out" | tail -1 | python3 -c '
import json
import sys

payload = json.loads(sys.stdin.read())
checks = payload.get("checks", {})
passed = [
    name
    for name, check in checks.items()
    if isinstance(check, dict) and check.get("ok") is True
]
print(f"{len(passed)} checks passed")
' 2>/dev/null || true)
      step_ok "settings smoke" "${smoke_summary:-passed}" "$(fmt_s $((SECONDS - smoke_start)))"
    fi
  fi

  if [[ "${JARVIS_SKIP_MEMORY_CORE_SMOKE:-0}" == "1" || "${JARVIS_ALPHA_SKIP_MEMORY_CORE_SMOKE:-0}" == "1" ]]; then
    printf '  %b⏭%b %-22s %-45s %s\n' "$YELLOW" "$RESET" "memory core smoke" "SKIPPED (JARVIS_SKIP_MEMORY_CORE_SMOKE=1)" ""
  else
    local memory_start=$SECONDS
    local memory_out
    local memory_ec

    memory_out=$(
      MEMORY_CORE_SMOKE_BASE_URL="$settings_base_url" \
      MEMORY_CORE_SMOKE_TOKEN_SSH_TARGET="$BRAIN" \
      MEMORY_CORE_SMOKE_DB_SSH_TARGET="$BRAIN" \
        python3 "$REPO_DIR/scripts/smoke_memory_core.py" 2>&1
    )
    memory_ec=$?
    if [ $memory_ec -ne 0 ]; then
      step_fail "memory core smoke" "failed"
      echo "$memory_out" >&2
      smoke_failed=1
    else
      local memory_summary
      memory_summary=$(printf '%s\n' "$memory_out" | tail -1 | python3 -c '
import json
import sys

payload = json.loads(sys.stdin.read())
checks = payload.get("checks", {})
passed = [
    name
    for name, check in checks.items()
    if isinstance(check, dict) and check.get("status") == "passed"
]
print(f"{len(passed)} checks passed")
' 2>/dev/null || true)
      step_ok "memory core smoke" "${memory_summary:-passed}" "$(fmt_s $((SECONDS - memory_start)))"
    fi
  fi

  if [[ "${JARVIS_SKIP_MEMORY_GRAPH_SMOKE:-0}" == "1" || "${JARVIS_ALPHA_SKIP_MEMORY_GRAPH_SMOKE:-0}" == "1" ]]; then
    printf '  %b⏭%b %-22s %-45s %s\n' "$YELLOW" "$RESET" "memory graph smoke" "SKIPPED (JARVIS_SKIP_MEMORY_GRAPH_SMOKE=1)" ""
  else
    local graph_start=$SECONDS
    local graph_out
    local graph_ec

    graph_out=$(
      MEMORY_GRAPH_SMOKE_BASE_URL="$settings_base_url" \
      MEMORY_GRAPH_SMOKE_TOKEN_SSH_TARGET="$BRAIN" \
        python3 "$REPO_DIR/scripts/smoke_memory_graph.py" 2>&1
    )
    graph_ec=$?
    if [ $graph_ec -ne 0 ]; then
      step_fail "memory graph smoke" "failed"
      echo "$graph_out" >&2
      smoke_failed=1
    else
      local graph_summary
      graph_summary=$(printf '%s\n' "$graph_out" | tail -1 | python3 -c '
import json
import sys

payload = json.loads(sys.stdin.read())
checks = payload.get("checks", {})
passed = [
    name
    for name, check in checks.items()
    if isinstance(check, dict) and check.get("status") == "passed"
]
print(f"{len(passed)} checks passed")
' 2>/dev/null || true)
      step_ok "memory graph smoke" "${graph_summary:-passed}" "$(fmt_s $((SECONDS - graph_start)))"
    fi
  fi

  if [[ "${JARVIS_SKIP_MEMORY_ASK_SMOKE:-0}" == "1" || "${JARVIS_ALPHA_SKIP_MEMORY_ASK_SMOKE:-0}" == "1" ]]; then
    printf '  %b⏭%b %-22s %-45s %s\n' "$YELLOW" "$RESET" "memory ask smoke" "SKIPPED (JARVIS_SKIP_MEMORY_ASK_SMOKE=1)" ""
  else
    local memory_ask_start=$SECONDS
    local memory_ask_out
    local memory_ask_ec

    memory_ask_out=$(
      HELM_MEMORY_ASK_SMOKE_BASE_URL="$settings_base_url" \
      HELM_MEMORY_ASK_SMOKE_TOKEN_SSH_TARGET="$BRAIN" \
        python3 "$REPO_DIR/scripts/smoke_helm_memory_ask_session.py" 2>&1
    )
    memory_ask_ec=$?
    if [ $memory_ask_ec -ne 0 ]; then
      step_fail "memory ask smoke" "failed"
      echo "$memory_ask_out" >&2
      smoke_failed=1
    else
      local memory_ask_summary
      memory_ask_summary=$(printf '%s\n' "$memory_ask_out" | tail -1 | python3 -c '
import json
import sys

payload = json.loads(sys.stdin.read())
checks = payload.get("checks", {})
passed = [
    name
    for name, check in checks.items()
    if check is True
]
print(f"{len(passed)} checks passed")
' 2>/dev/null || true)
      step_ok "memory ask smoke" "${memory_ask_summary:-passed}" "$(fmt_s $((SECONDS - memory_ask_start)))"
    fi
  fi

  if [[ "${JARVIS_SKIP_BEACON_SMOKE:-0}" == "1" || "${JARVIS_ALPHA_SKIP_BEACON_SMOKE:-0}" == "1" ]]; then
    printf '  %b⏭%b %-22s %-45s %s\n' "$YELLOW" "$RESET" "beacon smoke" "SKIPPED (JARVIS_SKIP_BEACON_SMOKE=1)" ""
  else
    local beacon_start=$SECONDS
    local beacon_out
    local beacon_ec

    beacon_out=$(
      ALPHA_BASE_URL="$settings_base_url" \
      BEACON_SMOKE_TOKEN_SSH_TARGET="$BRAIN" \
      BEACON_SMOKE_SKIP_AGENT=1 \
        python3 "$REPO_DIR/scripts/smoke_beacon_production.py" --skip-agent 2>&1
    )
    beacon_ec=$?
    if [ $beacon_ec -ne 0 ]; then
      step_fail "beacon smoke" "failed"
      echo "$beacon_out" >&2
      smoke_failed=1
    else
      local beacon_summary
      beacon_summary=$(printf '%s\n' "$beacon_out" | tail -1 | python3 -c '
import json
import sys

payload = json.loads(sys.stdin.read())
health = payload.get("results", {}).get("health", {})
status = health.get("status", "unknown")
warnings = health.get("warning_checks") or []
if warnings:
    print(f"health {status}; warnings={','.join(warnings)}")
else:
    print(f"health {status}; no warnings")
' 2>/dev/null || true)
      step_ok "beacon smoke" "${beacon_summary:-passed}" "$(fmt_s $((SECONDS - beacon_start)))"
    fi
  fi

  if [[ "${JARVIS_BEACON_BROWSER_CLICK_SMOKE:-0}" == "1" || "${JARVIS_ALPHA_BEACON_BROWSER_CLICK_SMOKE:-0}" == "1" ]]; then
    local browser_click_start=$SECONDS
    local browser_click_out
    local browser_click_ec

    browser_click_out=$(
      ALPHA_BASE_URL="$settings_base_url" \
      BEACON_SMOKE_TOKEN_SSH_TARGET="$BRAIN" \
        python3 "$REPO_DIR/scripts/smoke_beacon_production.py" --skip-agent --run-browser-click 2>&1
    )
    browser_click_ec=$?
    if [ $browser_click_ec -ne 0 ]; then
      step_fail "beacon browser click" "failed"
      echo "$browser_click_out" >&2
      smoke_failed=1
    else
      local browser_click_summary
      browser_click_summary=$(printf '%s\n' "$browser_click_out" | tail -1 | python3 -c '
import json
import sys

payload = json.loads(sys.stdin.read())
click = payload.get("results", {}).get("browser_click", {})
print(f"click={click.get('click_succeeded')}; audit={click.get('action_audit_count')}")
' 2>/dev/null || true)
      step_ok "beacon browser click" "${browser_click_summary:-passed}" "$(fmt_s $((SECONDS - browser_click_start)))"
    fi
  else
    printf '  %b⏭%b %-22s %-45s %s\n' "$YELLOW" "$RESET" "beacon browser click" "SKIPPED (set JARVIS_BEACON_BROWSER_CLICK_SMOKE=1)" ""
  fi

  if [[ "${JARVIS_SKIP_BEACON_ANSWER_EVAL:-0}" == "1" || "${JARVIS_ALPHA_SKIP_BEACON_ANSWER_EVAL:-0}" == "1" ]]; then
    printf '  %b⏭%b %-22s %-45s %s\n' "$YELLOW" "$RESET" "beacon answer eval" "SKIPPED (JARVIS_SKIP_BEACON_ANSWER_EVAL=1)" ""
  else
    local answer_eval_start=$SECONDS
    local answer_eval_out
    local answer_eval_ec

    answer_eval_out=$(
      cd "$REPO_DIR" && uv run --python 3.12 python scripts/eval_beacon_answer_engine.py 2>&1
    )
    answer_eval_ec=$?
    if [ $answer_eval_ec -ne 0 ]; then
      step_fail "beacon answer eval" "failed"
      echo "$answer_eval_out" >&2
      smoke_failed=1
    else
      local answer_eval_summary
      answer_eval_summary=$(printf '%s\n' "$answer_eval_out" | tail -1 | python3 -c '
import json
import sys

payload = json.loads(sys.stdin.read())
print(f"{payload.get('passed', 0)} checks passed")
' 2>/dev/null || true)
      step_ok "beacon answer eval" "${answer_eval_summary:-passed}" "$(fmt_s $((SECONDS - answer_eval_start)))"
    fi
  fi

  if [[ "${JARVIS_SKIP_MEMORY_CONTEXT_EVAL:-0}" == "1" || "${JARVIS_ALPHA_SKIP_MEMORY_CONTEXT_EVAL:-0}" == "1" ]]; then
    printf '  %b⏭%b %-22s %-45s %s\n' "$YELLOW" "$RESET" "memory context eval" "SKIPPED (JARVIS_SKIP_MEMORY_CONTEXT_EVAL=1)" ""
  else
    local memory_eval_start=$SECONDS
    local memory_eval_out
    local memory_eval_ec

    memory_eval_out=$(
      cd "$REPO_DIR" && uv run --python 3.12 python scripts/eval_memory_context.py 2>&1
    )
    memory_eval_ec=$?
    if [ $memory_eval_ec -ne 0 ]; then
      step_fail "memory context eval" "failed"
      echo "$memory_eval_out" >&2
      smoke_failed=1
    else
      local memory_eval_summary
      memory_eval_summary=$(printf '%s\n' "$memory_eval_out" | tail -1 | python3 -c '
import json
import sys

payload = json.loads(sys.stdin.read())
print(f"{payload.get('passed', 0)} checks passed")
' 2>/dev/null || true)
      step_ok "memory context eval" "${memory_eval_summary:-passed}" "$(fmt_s $((SECONDS - memory_eval_start)))"
    fi
  fi

  return $smoke_failed
}

cd "$REPO_DIR"

# ══════════════════════════════════════════════════════════
# ── Pre-flight: must be on main, clean, fast-forward ─
# ══════════════════════════════════════════════════════════
phase_header "PRE-FLIGHT"

CURRENT_BRANCH=$(git branch --show-current)
if [[ "$CURRENT_BRANCH" != "main" ]]; then
  step_fail "branch" "must be on main (currently on '$CURRENT_BRANCH')"
  printf '  Run: git checkout main && bash %s\n' "$0" >&2
  exit 1
fi
step_ok "branch" "on main"

if [ -n "$(git status --porcelain)" ]; then
  step_fail "tree" "working tree is dirty — commit or stash first"
  git status --short >&2
  exit 1
fi
step_ok "tree" "clean"

ff_start=$SECONDS
ff_log=$(mktemp)
if ! git pull --ff-only origin main >"$ff_log" 2>&1; then
  step_fail "git pull --ff-only" "main has diverged; resolve manually"
  cat "$ff_log" >&2
  rm -f "$ff_log"
  exit 1
fi
rm -f "$ff_log"
step_ok "git pull --ff-only" "up to date" "$(fmt_s $((SECONDS - ff_start)))"

LOCAL_HEAD=$(git rev-parse HEAD)
ORIGIN_HEAD=$(git rev-parse origin/main)
if [[ "$LOCAL_HEAD" != "$ORIGIN_HEAD" ]]; then
  step_fail "head check" "local HEAD does not match origin/main"
  printf '    local:  %s\n' "$LOCAL_HEAD" >&2
  printf '    origin: %s\n' "$ORIGIN_HEAD" >&2
  exit 1
fi
HEAD_AFTER=$(git rev-parse --short HEAD)
step_ok "head check" "$HEAD_AFTER · matches origin/main"

# ══════════════════════════════════════════════════════════
# ── HEADER ─
# ══════════════════════════════════════════════════════════
printf '\n%b══ ALPHA FAN-OUT %s%b\n' "$BOLD$CYAN" "═════════════════════════════════════════════════════" "$RESET"
printf '  Commit:  %s\n' "$HEAD_AFTER"
printf '  Start:   %s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')"
printf '  Log:     %s\n' "$LOG_FILE"

# ══════════════════════════════════════════════════════════
# ── UI build (so endpoint scp has a current dist) ─
# ══════════════════════════════════════════════════════════
if [[ -d "$REPO_DIR/ui/src" ]]; then
  phase_header "UI BUILD"
  ui_start=$SECONDS
  ui_output=$(bash "$REPO_DIR/scripts/build_alpha_ui.sh" 2>&1)
  ui_ec=$?
  if [ $ui_ec -ne 0 ]; then
    step_fail "ui build" "vite failed"
    echo "$ui_output" >&2
    exit 1
  fi
  ui_summary=$(echo "$ui_output" | grep -E "built in|modules transformed" | tail -1 | sed 's/^[ \t]*//')
  step_ok "ui build" "${ui_summary:-built}" "$(fmt_s $((SECONDS - ui_start)))"
fi

# ══════════════════════════════════════════════════════════
# ── Classifier: docs/handoffs-only fan-out skip (TD-96) ─
# ══════════════════════════════════════════════════════════
# Predicate: skip fan-out iff every changed file in the just-merged commit
# matches ^docs/handoffs/. One non-handoff file → full fan-out. Empty diff
# (defensive) → fan-out. Mirrors GitHub Actions paths-ignore semantics.
CHANGED_FILES=$(git diff --name-only HEAD~1 HEAD)
if [ -z "$CHANGED_FILES" ]; then
  HANDOFF_ONLY=false
else
  NON_HANDOFF=$(echo "$CHANGED_FILES" | grep -v '^docs/handoffs/' | wc -l | tr -d ' ')
  if [ "$NON_HANDOFF" = "0" ]; then
    HANDOFF_ONLY=true
  else
    HANDOFF_ONLY=false
  fi
fi

if [ "$HANDOFF_ONLY" = "true" ]; then
  phase_header "FAN-OUT"
  step_ok "classifier" "docs/handoffs only — skipping fan-out"
  total_dur=$((SECONDS - DEPLOY_START))
  done_banner "$HEAD_AFTER" "$total_dur"
  exit 0
fi

# ── Classification moved to pull script (TD-107) ──
# Deploy script is dumb orchestrator — pull script self-classifies restarts

# ══════════════════════════════════════════════════════════
# ── FAN-OUT ─
# ══════════════════════════════════════════════════════════
phase_header "FAN-OUT"

# Sandbox auto-pull
if [[ "${JARVIS_SKIP_SANDBOX:-0}" == "1" ]]; then
  printf '  %b⏭%b %-22s %-45s %s\n' "$YELLOW" "$RESET" "sandbox" "SKIPPED (JARVIS_SKIP_SANDBOX=1)" ""
else
  sb_start=$SECONDS
  sb_out=$(ssh "${SSH_OPTS[@]}" "$SANDBOX" \
    "bash -s" < "${REPO_DIR}/scripts/sandbox_safe_pull.sh" 2>&1)
  sb_ec=$?
  sb_dur=$((SECONDS - sb_start))
  if [ $sb_ec -eq 0 ]; then
    sb_hash=$(echo "$sb_out" | tail -1 | tr -d '\r\n')
    step_ok "sandbox" "pulled — $sb_hash" "$(fmt_s $sb_dur)"
  else
    step_fail "sandbox" "pull failed"
    echo "$sb_out" >&2
    DEPLOY_FAILED=1
  fi
fi

# Endpoint SCP dist — only after Sandbox is clean/current.
if [ $DEPLOY_FAILED -eq 0 ]; then
  scp_start=$SECONDS
  scp_out=$(scp "${SSH_OPTS[@]}" -r "$REPO_DIR/ui/dist" "$ENDPOINT:~/jarvis-alpha/ui/" 2>&1)
  scp_ec=$?
  scp_dur=$((SECONDS - scp_start))
  if [ $scp_ec -eq 0 ]; then
    step_ok "endpoint (scp)" "ui dist synced" "$(fmt_s $scp_dur)"
  else
    step_fail "endpoint (scp)" "scp failed"
    echo "$scp_out" >&2
    DEPLOY_FAILED=1
  fi
fi

# SSH fan-out: Brain → Gateway → Endpoint (halt on failure)
# TD-107: always pull all runtime nodes; pull script decides whether to restart
if [ $DEPLOY_FAILED -eq 0 ]; then
  remote_pull "Brain" "$BRAIN" || exit 1
  remote_pull "Gateway" "$GATEWAY" || exit 1
  remote_pull "Endpoint" "$ENDPOINT" || exit 1
fi

if [ $DEPLOY_FAILED -eq 0 ]; then
  run_post_deploy_smokes || DEPLOY_FAILED=1
fi

# ══════════════════════════════════════════════════════════
# ── DONE ─
# ══════════════════════════════════════════════════════════
if [ $DEPLOY_FAILED -eq 0 ]; then
  total_dur=$((SECONDS - DEPLOY_START))
  done_banner "$HEAD_AFTER" "$total_dur"
  exit 0
else
  printf '\n%b══ FAILED ═════════════════════════════════════════════%b\n' "$RED$BOLD" "$RESET" >&2
  printf '  See diagnostics above.\n' >&2
  printf '  Full log: %s\n' "$LOG_FILE" >&2
  exit 1
fi
