#!/bin/bash
# jarvisalpha_commit.sh — Commit + push + open PR for jarvis-alpha (P-trait).
#
# jarvis-alpha is P-trait per ADR-0005: every change reaches main via PR review,
# never direct push. This script: ruff/UI build → commit → push current branch
# → open PR. Fan-out to nodes is a separate post-merge step.
#
# After the PR merges, run `scripts/jarvisalpha_deploy.sh` from main to fan out
# to all nodes (Brain, Gateway, Endpoint, Sandbox).
#
# Usage:
#   bash scripts/jarvisalpha_commit.sh "<commit message>"
#   bash scripts/jarvisalpha_commit.sh --auto-merge "<commit message>"
#
# Flags:
#   --auto-merge   After PR is opened, enable GitHub auto-merge (squash + delete branch).
#                  PR auto-merges once branch protection checks pass.
#
# Full log always written to /tmp/jarvisalpha_commit_YYYYMMDD_HHMMSS.log

set -uo pipefail

# ── Config ────────────────────────────────────────────────
REPO_DIR="${HOME}/jarvis-alpha"

# ── Args ──────────────────────────────────────────────────
AUTO_MERGE=0
COMMIT_MSG=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --auto-merge)
      AUTO_MERGE=1
      shift
      ;;
    -h|--help)
      sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      if [[ -z "$COMMIT_MSG" ]]; then
        COMMIT_MSG="$1"
      fi
      shift
      ;;
  esac
done
COMMIT_MSG="${COMMIT_MSG:-update}"

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
SCRIPT_START=$SECONDS

# ── Helpers ───────────────────────────────────────────────
phase_header() {
  local label="$1"
  printf '\n%b── %s %s%b\n' "$CYAN" "$label" "─────────────────────────────────────────────────────" "$RESET"
}

done_banner() {
  local hash="$1"
  local dur="$2"
  local pr_url="$3"
  printf '\n%b══ DONE %s%b\n' "$BOLD$GREEN" "═════════════════════════════════════════════════════" "$RESET"
  printf '  ALPHA %b✅%b %s pushed in %ds\n' "$GREEN" "$RESET" "$hash" "$dur"
  printf '\n'
  [ -n "$pr_url" ] && printf '  PR:    %s\n' "$pr_url"
  printf '  Log:   %s\n' "$LOG_FILE"
  printf '  Next:  PR review → merge → bash scripts/jarvisalpha_deploy.sh\n'
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

fmt_s() {
  awk -v s="$1" 'BEGIN { if (s < 10) printf "%.1fs", s; else printf "%ds", s }'
}

cd "$REPO_DIR"

# ══════════════════════════════════════════════════════════
# ── Branch guard (P-trait — never commit on main) ─
# ══════════════════════════════════════════════════════════
BRANCH=$(git branch --show-current)
if [[ "$BRANCH" == "main" || "$BRANCH" == "master" ]]; then
  printf '%bERROR: jarvis-alpha is P-trait. Branch first:%b\n' "$RED$BOLD" "$RESET" >&2
  printf '  jarvis_branch claude-code/<descriptor>  (agent work)\n' >&2
  printf '  jarvis_branch feature/<descriptor>      (human work)\n' >&2
  exit 1
fi
case "$BRANCH" in
  feature/*|claude-code/*|hotfix/*|chore/*) ;;
  *)
    printf 'ERROR: Branch name '\''%s'\'' must start with one of: feature/ claude-code/ hotfix/ chore/\n' "$BRANCH" >&2
    exit 4
    ;;
esac

# ══════════════════════════════════════════════════════════
# ── Detect .py changes for ruff gating ─
# ══════════════════════════════════════════════════════════
py_changed=false
if git diff --name-only HEAD 2>/dev/null | grep -qE '\.py$'; then py_changed=true; fi
if git ls-files -o --exclude-standard | grep -qE '\.py$'; then py_changed=true; fi

# ══════════════════════════════════════════════════════════
# ── HEADER ─
# ══════════════════════════════════════════════════════════
HEAD_BEFORE=$(git rev-parse --short HEAD)
printf '\n%b══ ALPHA COMMIT %s%b\n' "$BOLD$CYAN" "═════════════════════════════════════════════════════" "$RESET"
printf '  Branch:  %s\n' "$BRANCH"
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

# Push current branch
push_start=$SECONDS
push_log=$(mktemp)
if ! git push -u origin "$BRANCH" >"$push_log" 2>&1; then
  step_fail "git push" "failed"
  cat "$push_log" >&2
  rm -f "$push_log"
  exit 1
fi
rm -f "$push_log"
step_ok "git push" "origin/$BRANCH" "$(fmt_s $((SECONDS - push_start)))"

# ══════════════════════════════════════════════════════════
# ── PR ─
# ══════════════════════════════════════════════════════════
phase_header "PR"

PR_URL=""
pr_start=$SECONDS
if gh pr view "$BRANCH" >/dev/null 2>&1; then
  PR_URL=$(gh pr view "$BRANCH" --json url -q .url 2>/dev/null || true)
  step_ok "gh pr" "already open" "$(fmt_s $((SECONDS - pr_start)))"
else
  pr_log=$(mktemp)
  if ! gh pr create --fill --base main >"$pr_log" 2>&1; then
    step_fail "gh pr create" "failed"
    cat "$pr_log" >&2
    rm -f "$pr_log"
    exit 1
  fi
  PR_URL=$(grep -Eo 'https://github\.com/[^[:space:]]+' "$pr_log" | head -1 || true)
  rm -f "$pr_log"
  step_ok "gh pr create" "${PR_URL:-opened}" "$(fmt_s $((SECONDS - pr_start)))"
fi

if [[ "$AUTO_MERGE" == "1" ]]; then
  am_start=$SECONDS
  am_log=$(mktemp)
  if ! gh pr merge --auto --squash --delete-branch >"$am_log" 2>&1; then
    step_fail "gh pr merge --auto" "failed"
    cat "$am_log" >&2
    rm -f "$am_log"
    exit 1
  fi
  rm -f "$am_log"
  step_ok "gh pr merge" "auto-merge enabled (squash, delete-branch)" "$(fmt_s $((SECONDS - am_start)))"
fi

# ══════════════════════════════════════════════════════════
# ── DONE ─
# ══════════════════════════════════════════════════════════
total_dur=$((SECONDS - SCRIPT_START))
done_banner "$HEAD_AFTER" "$total_dur" "$PR_URL"
exit 0
