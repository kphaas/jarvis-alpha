#!/bin/bash
set -uo pipefail

# ── Config ────────────────────────────────────────────────
BRAIN="jarvisbrain@100.64.166.22"
GATEWAY="infranet@100.112.63.25"
ENDPOINT="jarvisendpoint@100.87.223.31"
SANDBOX="jarvissand@100.124.172.14"
SSH_KEY="${HOME}/.ssh/macair_jarvis"
SSH_OPTS=(-i "$SSH_KEY" -o IdentitiesOnly=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no)
REPO_DIR="${HOME}/jarvis-alpha"
COMMIT_MSG="${1:-update}"

# ── Colors ────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
RESET='\033[0m'
BOLD='\033[1m'
DIM='\033[2m'

# ── Helper: aligned status line ───────────────────────────
# Usage: status_line "✅" "Sandbox" "pulled — cb9670e"
status_line() {
  local icon="$1"
  local label="$2"
  local detail="$3"
  printf '%b  %-12s %b\n' "$icon" "$label" "$detail"
}

# ── Helper: error box (bold red, only on failure) ─────────
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

# ── Step 1 — ruff format + lint ───────────────────────────
cd "$REPO_DIR"
py_changed=false
if git diff --name-only HEAD 2>/dev/null | grep -qE '\.py$'; then py_changed=true; fi
if git ls-files -o --exclude-standard | grep -qE '\.py$'; then py_changed=true; fi

if [[ "$py_changed" == true ]]; then
  if command -v ruff &>/dev/null; then
    echo "Running ruff format..."
    ruff format brain/ --quiet || true
    echo "Running ruff lint..."
    ruff check brain/ --quiet --fix || true
  fi
fi

# ── Step 2 — UI build ─────────────────────────────────────
if [[ -d "$REPO_DIR/ui/src" ]]; then
  printf '%s' "Building UI... "
  ui_build_output=$( (cd "$REPO_DIR/ui" && npm run build --silent) 2>&1 ) || {
    printf '%b\n' "${RED}FAILED${RESET}" >&2
    error_box "UI build failed" "Vite returned non-zero" "See output below for details"
    printf '%s\n' "$ui_build_output" >&2
    exit 1
  }
  ui_build_summary=$(printf '%s\n' "$ui_build_output" | grep -E "built in|modules transformed" | tail -1)
  printf '%b %s\n' "${GREEN}✅${RESET}" "$ui_build_summary"
fi

# ── Step 3 — Commit and push (hardened) ───────────────────
# Hard fail on empty index. Override with ALLOW_EMPTY_DEPLOY=1
# Tech debt tracked: TD-7 (shellcheck), TD-8 (refactor to functions), TD-9 (pin SHA on remote)

printf '\n%b\n' "${CYAN}── PRE-STAGE STATUS ─────────────────────────────────────${RESET}"
printf '%s\n' "Host:   $(hostname -s)"
printf '%s\n' "Branch: $(git branch --show-current)"
printf '%s\n' "HEAD:   $(git rev-parse --short HEAD) — $(git log -1 --format=%s)"
printf '\n'
PRE_STATUS=$(git status --short)
if [[ -z "$PRE_STATUS" ]]; then
  printf '%b\n' "${YELLOW}Working tree CLEAN — no local changes detected${RESET}"
else
  printf '%s\n' "Working tree changes:"
  printf '%s\n' "$PRE_STATUS" | sed 's/^/  /'
fi
printf '%b\n\n' "${CYAN}─────────────────────────────────────────────────────────${RESET}"

head_before=$(git rev-parse HEAD) || { printf '%b\n' "${RED}ERROR: git rev-parse HEAD failed${RESET}" >&2; exit 1; }

git add -A || { error_box "git add -A failed" "Working tree may be locked or corrupted"; exit 1; }

if git diff --cached --quiet; then
  if [[ "${ALLOW_EMPTY_DEPLOY:-0}" != "1" ]]; then
    error_box "No staged changes on $(hostname -s)" \
      "Your expected work may be on a DIFFERENT MACHINE" \
      "HEAD remains: ${head_before:0:12}" \
      "To redeploy: ALLOW_EMPTY_DEPLOY=1 bash $0 \"$COMMIT_MSG\""
    exit 1
  fi
  printf '%b\n' "${YELLOW}WARNING: REDEPLOYING EXISTING COMMIT ${head_before}${RESET}" >&2
  printf '%b\n' "${YELLOW}         (ALLOW_EMPTY_DEPLOY=1 set — proceeding without new commit)${RESET}" >&2
else
  printf '%b\n' "${GREEN}Staged for commit:${RESET}"
  git diff --cached --name-only | sed 's/^/  /'
  git commit -m "$COMMIT_MSG" || { error_box "git commit failed" "Check pre-commit hooks or commit message"; exit 1; }
  head_after=$(git rev-parse HEAD) || { error_box "git rev-parse HEAD failed after commit"; exit 1; }
  if [[ "$head_after" == "$head_before" ]]; then
    error_box "Commit reported success but HEAD did not advance" \
      "HEAD: ${head_before:0:12} (unchanged)" \
      "Possible cause: commit hook silently rejected the commit"
    exit 1
  fi
  printf '%b\n' "${GREEN}✅ Commit created: ${head_after}${RESET}"
fi

printf '\n%s\n' "Pulling rebased main..."
git pull origin main --rebase || { error_box "git pull --rebase failed" "Resolve conflicts and retry"; exit 1; }

printf '%s\n' "Pushing to origin/main..."
git push origin main || { error_box "git push failed" "Check network and GitHub auth"; exit 1; }
printf '%b\n' "${GREEN}✅ Pushed to origin/main${RESET}"

# ── Step 4 — Detect changed files ─────────────────────────
CHANGED=$(git diff --name-only HEAD~1 HEAD 2>/dev/null || git show --name-only --format="" HEAD)

# ── Step 5 — Classify changes ─────────────────────────────
NEEDS_BRAIN=false
NEEDS_GATEWAY=false
NEEDS_ENDPOINT=false
NEEDS_SANDBOX=true
MANUAL_BRAIN=false
MANUAL_GATEWAY=false
MANUAL_ENDPOINT=false

while IFS= read -r f; do
  [[ -z "$f" ]] && continue
  case "$f" in
    brain/services/*)   MANUAL_BRAIN=true ;;
    gateway/services/*) MANUAL_GATEWAY=true ;;
    endpoint/*)         MANUAL_ENDPOINT=true ;;
  esac
  if [[ "$f" == *.py || "$f" == *.yaml || "$f" == *.yml || "$f" == *.md || "$f" == *.sh ]]; then
    NEEDS_BRAIN=true
    NEEDS_GATEWAY=true
    NEEDS_ENDPOINT=true
  fi
  if [[ "$f" == brain/* ]]; then NEEDS_BRAIN=true; fi
  if [[ "$f" == gateway/* ]]; then NEEDS_GATEWAY=true; fi
  if [[ "$f" == endpoint/* ]]; then NEEDS_ENDPOINT=true; fi
done <<< "$CHANGED"

# ── Step 6 — Deploy plan (compact / expanded based on manual needs) ─
HAS_MANUAL=false
if $MANUAL_BRAIN || $MANUAL_GATEWAY || $MANUAL_ENDPOINT; then HAS_MANUAL=true; fi

if ! $HAS_MANUAL; then
  # Compact one-liner — no manual action required
  needs_list=""
  $NEEDS_BRAIN    && needs_list="${needs_list}Brain "
  $NEEDS_GATEWAY  && needs_list="${needs_list}Gateway "
  $NEEDS_ENDPOINT && needs_list="${needs_list}Endpoint "
  if [[ -n "$needs_list" ]]; then
    printf '\n%bDeploy:%b Sandbox auto / pull required on: %s\n\n' "${CYAN}" "${RESET}" "$needs_list"
  else
    printf '\n%bDeploy:%b Sandbox auto / no other nodes affected\n\n' "${CYAN}" "${RESET}"
  fi
else
  # Expanded — manual deploy required, show full table
  printf '\n%b── ALPHA DEPLOY PLAN ────────────────────────────────────%b\n' "${CYAN}" "${RESET}"
  printf '%s\n' "Changed files:"
  if [[ -n "$CHANGED" ]]; then
    printf '%s\n' "$CHANGED" | sed 's/^/  /'
  fi
  printf '\n'
  $MANUAL_BRAIN   && status_line "${YELLOW}⚠️${RESET}" "Brain"    "${YELLOW}MANUAL pull required${RESET}"
  $MANUAL_GATEWAY && status_line "${YELLOW}⚠️${RESET}" "Gateway"  "${YELLOW}MANUAL pull required${RESET}"
  $MANUAL_ENDPOINT && status_line "${YELLOW}⚠️${RESET}" "Endpoint" "${YELLOW}MANUAL pull required${RESET}"
  status_line "${GREEN}✅${RESET}" "Sandbox" "auto-pull"
  printf '\n'
  printf '%bRun on each manual node:%b\n' "${YELLOW}" "${RESET}"
  $MANUAL_BRAIN    && printf '  ssh jarvisbrain@100.64.166.22 "bash ~/jarvis-alpha/scripts/jarvisalpha_pull.sh"\n'
  $MANUAL_GATEWAY  && printf '  ssh infranet@100.112.63.25 "bash ~/jarvis-alpha/scripts/jarvisalpha_pull.sh"\n'
  $MANUAL_ENDPOINT && printf '  ssh jarvisendpoint@100.87.223.31 "bash ~/jarvis-alpha/scripts/jarvisalpha_pull.sh"\n'
  printf '%b─────────────────────────────────────────────────────────%b\n\n' "${CYAN}" "${RESET}"
fi

# ── Step 7 — Sandbox auto-pull ────────────────────────────
pull_ok=0
sandbox_footer=""

pull_output=$(ssh "${SSH_OPTS[@]}" "$SANDBOX" bash -s 2>&1 <<'REMOTE'
cd ~/jarvis-alpha && git pull origin main --rebase && git rev-parse --short HEAD
REMOTE
)
pull_ec=$?
if [[ $pull_ec -eq 0 ]]; then
  sandbox_short=$(echo "$pull_output" | tail -1 | tr -d '\r\n')
  status_line "${GREEN}✅${RESET}" "Sandbox" "pulled — ${sandbox_short}"
  sandbox_footer="pulled ✅ ($sandbox_short)"
  pull_ok=1
else
  status_line "${RED}❌${RESET}" "Sandbox" "${RED}pull failed${RESET}"
  error_box "Sandbox pull failed" "See output below"
  echo "$pull_output" >&2
  sandbox_footer="pull failed ❌"
fi

# ── Step 8 — SCP dist to Endpoint ────────────────────────
ENDPOINT_HOST="jarvisendpoint@100.87.223.31"
scp_output=$(scp "${SSH_OPTS[@]}" -r "$REPO_DIR/ui/dist" "$ENDPOINT_HOST:~/jarvis-alpha/ui/" 2>&1)
scp_ec=$?
if [[ $scp_ec -eq 0 ]]; then
  status_line "${GREEN}✅${RESET}" "Endpoint" "UI dist synced"
else
  status_line "${RED}❌${RESET}" "Endpoint" "${RED}scp failed${RESET}"
  error_box "UI dist scp to Endpoint failed" "See output below"
  echo "$scp_output" >&2
fi

# ── Step 9 — Intel refresh on Sandbox ─────────────────────
if [[ $pull_ok -eq 1 ]]; then
  echo ""
  echo "Triggering intel refresh for jarvis-alpha (project 65)..."
  ssh "${SSH_OPTS[@]}" "$SANDBOX" \
    "body=\$(curl -sk -X POST 'http://localhost:5001/api/intel/refresh?project_id=65' --max-time 30); \
     if [ -z \"\$body\" ]; then echo 'Intel refresh: forge offline — skipped'; \
     else echo \"\$body\" | python3 -c \"import sys,json; d=json.load(sys.stdin); r=d.get('results',[{}])[0]; print('Intel:', r.get('symbols','?'), 'symbols' if 'symbols' in r else r.get('error','?'))\" 2>/dev/null || echo 'Intel refresh: unexpected response'; fi" \
    || echo "Intel refresh skipped"
fi

# ── Step 9 — Footer ───────────────────────────────────────
COMMIT_HASH=$(git -C "$REPO_DIR" rev-parse --short HEAD)
COMMIT_LINE=$(git -C "$REPO_DIR" log -1 --format=%s)
printf "\n%b ${CYAN}%s${RESET} — %s | sandbox: %s\n" "${GREEN}ALPHA ✅${RESET}" "$COMMIT_HASH" "$COMMIT_LINE" "$sandbox_footer"
