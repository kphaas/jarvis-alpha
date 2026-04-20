#!/bin/bash
# jarvisalpha_commit.sh — Commit + push + fan-out deploy for jarvis-alpha.
#
# Verbosity (additive, Ansible-style):
#   (default)   NORMAL — pretty event rendering via render_events.py
#   VERBOSE=1   -v      — raw human output from pull script visible alongside events
#   VERBOSE=2   -vv     — -v + raw ##EVT## JSON visible
#
# Full log always written to /tmp/jarvisalpha_commit_YYYYMMDD_HHMMSS.log

set -uo pipefail

# ── Config ────────────────────────────────────────────────
BRAIN="jarvisbrain@jarvis-brain.tail40ed36.ts.net"
GATEWAY="infranet@jarvis-gateway.tail40ed36.ts.net"
ENDPOINT="jarvisendpoint@jarvis-endpoint.tail40ed36.ts.net"
SANDBOX="jarvissand@jarvis-sandbox.tail40ed36.ts.net"
SSH_KEY="${HOME}/.ssh/macair_jarvis"
SSH_OPTS=(-i "$SSH_KEY" -o IdentitiesOnly=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no)
REPO_DIR="${HOME}/jarvis-alpha"
COMMIT_MSG="${1:-update}"
RENDERER="${REPO_DIR}/scripts/render_events.py"
VERBOSE="${VERBOSE:-0}"

# ── Log file ──────────────────────────────────────────────
LOG_TS=$(date +%Y%m%d_%H%M%S)
LOG_FILE="${LOG:-/tmp/jarvisalpha_commit_${LOG_TS}.log}"
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

# ── Helpers ───────────────────────────────────────────────
phase_header() {
  # Fixed-width headers — pad/truncate by character count, not byte count,
  # so multi-byte UTF-8 box-drawing chars aren't cut mid-character.
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
  printf '  Undo:  git revert %s && bash %s "revert: %s"\n' "$hash" "$0" "$hash"
  printf '\n'
}

# Render one pre-deploy step: "  ✅ name   detail   duration"
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

# Portable lowercase (bash 3.2 compatible — macOS /bin/bash is 3.2)
lc() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

fmt_s() {
  # Format seconds as "X.Xs" or integer for whole numbers
  awk -v s="$1" 'BEGIN { if (s < 10) printf "%.1fs", s; else printf "%ds", s }'
}

# Time a command, capture stdout/stderr + exit code + duration
# Usage: time_step "step name" "detail on success" COMMAND...
time_step() {
  local step="$1"; shift
  local detail="$1"; shift
  local start=$SECONDS
  local output
  local ec
  output=$("$@" 2>&1) && ec=0 || ec=$?
  local dur=$((SECONDS - start))
  if [ $ec -eq 0 ]; then
    step_ok "$step" "$detail" "$(fmt_s $dur)"
  else
    step_fail "$step" "failed (exit $ec)"
    printf '%b%s%b\n' "$DIM" "$output" "$RESET" >&2
    return $ec
  fi
}

# Unified failure box — takes node + failure JSON + pulls diagnostics
failure_box() {
  local node_label="$1"
  local node_host="$2"
  local fail_json="$3"

  # Parse the failure JSON via Python (same pattern as renderer)
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

  # Fetch diagnostics from failing node (separate SSH, 10s timeout)
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

# Run pull script on a remote node and pipe through renderer.
# On any ##RENDER_FAIL## sentinel, capture the JSON and trigger failure box.
remote_pull() {
  local node_label="$1"
  local node_host="$2"

  local start=$SECONDS
  local render_output
  local render_ec

  printf '\n  %s %s\n' "$node_label" "$(printf '%0.s.' $(seq 1 $((55 - ${#node_label}))))"

  # Capture renderer output so we can detect RENDER_FAIL sentinel
  local tmp_out
  tmp_out=$(mktemp)
  ssh "${SSH_OPTS[@]}" -o ServerAliveInterval=30 "$node_host" \
    "bash ~/jarvis-alpha/scripts/jarvisalpha_pull.sh" 2>&1 \
    | VERBOSE="$VERBOSE" python3 "$RENDERER" --node="$(lc "$node_label")" \
    > "$tmp_out"
  render_ec=$?

  # Strip internal sentinels from displayed output (keep them in log for debugging)
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

# ══════════════════════════════════════════════════════════
# ── Step 1: Ruff format + lint (only if .py files changed) ─
# ══════════════════════════════════════════════════════════
cd "$REPO_DIR"
py_changed=false
if git diff --name-only HEAD 2>/dev/null | grep -qE '\.py$'; then py_changed=true; fi
if git ls-files -o --exclude-standard | grep -qE '\.py$'; then py_changed=true; fi

# ══════════════════════════════════════════════════════════
# ── HEADER: commit + scope summary ─
# ══════════════════════════════════════════════════════════
HEAD_BEFORE=$(git rev-parse --short HEAD)
HEAD_MSG=$(git log -1 --format=%s)
printf '\n%b══ ALPHA DEPLOY %s%b\n' "$BOLD$CYAN" "═════════════════════════════════════════════════════" "$RESET"
printf '  Commit:  (pending)\n'
printf '  Message: %s\n' "$COMMIT_MSG"
printf '  Start:   %s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')"
printf '  Log:     %s\n' "$LOG_FILE"

# ══════════════════════════════════════════════════════════
# ── PRE-DEPLOY ─
# ══════════════════════════════════════════════════════════
phase_header "PRE-DEPLOY"

# Ruff (if needed)
if [[ "$py_changed" == true ]] && command -v ruff &>/dev/null; then
  ruff_start=$SECONDS
  ruff_out=$(ruff format . 2>&1)
  ruff_ec=$?
  if [ $ruff_ec -ne 0 ]; then
    step_fail "ruff format" "failed"
    echo "$ruff_out" >&2
    exit 1
  fi
  step_ok "ruff format" "clean" "$(fmt_s $((SECONDS - ruff_start)))"

  lint_start=$SECONDS
  lint_out=$(ruff check . 2>&1)
  lint_ec=$?
  if [ $lint_ec -ne 0 ]; then
    step_fail "ruff lint" "failed"
    echo "$lint_out" >&2
    exit 1
  fi
  step_ok "ruff lint" "clean" "$(fmt_s $((SECONDS - lint_start)))"
else
  step_ok "ruff" "skipped (no .py changes)"
fi

# UI build
if [[ -d "$REPO_DIR/ui/src" ]]; then
  ui_start=$SECONDS
  ui_output=$( (cd "$REPO_DIR/ui" && npm run build --silent) 2>&1 )
  ui_ec=$?
  if [ $ui_ec -ne 0 ]; then
    step_fail "ui build" "vite failed"
    echo "$ui_output" >&2
    exit 1
  fi
  ui_summary=$(echo "$ui_output" | grep -E "built in|modules transformed" | tail -1 | sed 's/^[ \t]*//')
  step_ok "ui build" "${ui_summary:-built}" "$(fmt_s $((SECONDS - ui_start)))"
fi

# Git commit + push
git add -A || { step_fail "git add" "failed"; exit 1; }

if git diff --cached --quiet; then
  if [[ "${ALLOW_EMPTY_DEPLOY:-0}" != "1" ]]; then
    step_fail "git commit" "no staged changes — working tree may be on wrong machine"
    printf '\n  To redeploy existing commit: ALLOW_EMPTY_DEPLOY=1 bash %s "%s"\n' "$0" "$COMMIT_MSG" >&2
    exit 1
  fi
  step_ok "git commit" "redeploy (no new changes)"
  HEAD_AFTER="$HEAD_BEFORE"
else
  # Forbidden path check
  forbidden_staged=()
  while IFS= read -r staged_path; do
    [[ -z "$staged_path" ]] && continue
    case "$staged_path" in
      .cursor_tmp_venv|.cursor_tmp_venv/*|.venv|.venv/*|venv|venv/*|env|env/*|node_modules|node_modules/*|__pycache__|__pycache__/*|*.pyc|.DS_Store|*/.DS_Store)
        forbidden_staged+=("$staged_path")
        ;;
    esac
  done < <(git diff --cached --name-only)

  if (( ${#forbidden_staged[@]} > 0 )); then
    step_fail "git commit" "forbidden paths staged"
    for p in "${forbidden_staged[@]}"; do printf '    %s\n' "$p" >&2; done
    exit 1
  fi

  commit_start=$SECONDS
  git commit -m "$COMMIT_MSG" >/dev/null 2>&1 || { step_fail "git commit" "commit failed"; exit 1; }
  HEAD_AFTER=$(git rev-parse --short HEAD)
  FILE_COUNT=$(git diff --name-only "${HEAD_BEFORE}..${HEAD_AFTER}" | wc -l | tr -d ' ')
  step_ok "git commit" "$HEAD_AFTER · $FILE_COUNT file$([ $FILE_COUNT -ne 1 ] && echo 's')" "$(fmt_s $((SECONDS - commit_start)))"
fi

# Pull rebase (silent unless fails)
pull_start=$SECONDS
if ! git pull origin main --rebase >/dev/null 2>&1; then
  step_fail "git pull --rebase" "resolve conflicts and retry"
  exit 1
fi
step_ok "git pull --rebase" "up to date" "$(fmt_s $((SECONDS - pull_start)))"

# Push
push_start=$SECONDS
push_log=$(mktemp)
if ! git push origin main >"$push_log" 2>&1; then
  step_fail "git push" "failed"
  cat "$push_log" >&2
  rm -f "$push_log"
  exit 1
fi
rm -f "$push_log"
step_ok "git push" "origin/main" "$(fmt_s $((SECONDS - push_start)))"

# ══════════════════════════════════════════════════════════
# ── Classifier: docs/handoffs-only fan-out skip (TD-96) ─
# ══════════════════════════════════════════════════════════
# Predicate: skip fan-out iff every changed file in the just-pushed commit
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
# Commit script is dumb orchestrator — pull script self-classifies restarts

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
    "cd ~/jarvis-alpha && git pull origin main --rebase --quiet && git rev-parse --short HEAD" 2>&1)
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

# Endpoint SCP dist
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

# SSH fan-out: Brain → Gateway → Endpoint (halt on failure)
# TD-107: always pull all runtime nodes; pull script decides whether to restart
if [ $DEPLOY_FAILED -eq 0 ]; then
  remote_pull "Brain" "$BRAIN" || exit 1
  remote_pull "Gateway" "$GATEWAY" || exit 1
  remote_pull "Endpoint" "$ENDPOINT" || exit 1
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
