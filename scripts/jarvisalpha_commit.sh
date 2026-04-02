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
  echo "Building UI..."
  (cd "$REPO_DIR/ui" && npm run build --silent) || {
    echo -e "${RED}UI build failed — aborting commit${RESET}" >&2
    exit 1
  }
  echo "UI build ✅"
fi

# ── Step 3 — Commit and push ──────────────────────────────
git add -A
if git diff --cached --quiet; then
  echo -e "${YELLOW}Nothing to commit${RESET}"
else
  git commit -m "$COMMIT_MSG"
fi
git pull origin main --rebase
git push origin main

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

# ── Step 6 — Deploy plan ──────────────────────────────────
echo ""
echo -e "${CYAN}── ALPHA DEPLOY PLAN ────────────────────────────────────${RESET}"
echo "Changed files:"
if [[ -n "$CHANGED" ]]; then
  echo "$CHANGED" | sed 's/^/  /'
else
  echo "  (none)"
fi
echo ""

brain_label="—"
gateway_label="—"
endpoint_label="—"
if $MANUAL_BRAIN;   then brain_label="${YELLOW}⚠️  manual required${RESET}"; fi
if $MANUAL_GATEWAY; then gateway_label="${YELLOW}⚠️  manual required${RESET}"; fi
if $MANUAL_ENDPOINT; then endpoint_label="${YELLOW}⚠️  manual required${RESET}"; fi
if $NEEDS_BRAIN && ! $MANUAL_BRAIN;   then brain_label="${CYAN}run jarvisalpha_pull.sh on Brain${RESET}"; fi
if $NEEDS_GATEWAY && ! $MANUAL_GATEWAY; then gateway_label="${CYAN}run jarvisalpha_pull.sh on Gateway${RESET}"; fi
if $NEEDS_ENDPOINT && ! $MANUAL_ENDPOINT; then endpoint_label="${CYAN}run jarvisalpha_pull.sh on Endpoint${RESET}"; fi

echo -e "  Brain:    $brain_label"
echo -e "  Gateway:  $gateway_label"
echo -e "  Endpoint: $endpoint_label"
echo -e "  Sandbox:  ${GREEN}✅ auto-pull${RESET}"
echo ""

if $MANUAL_BRAIN || $MANUAL_GATEWAY || $MANUAL_ENDPOINT; then
  echo -e "${YELLOW}⚠️  Services changed — manual deploy required on affected nodes:${RESET}"
  $MANUAL_BRAIN   && echo "     Brain:   ssh jarvisbrain@100.64.166.22 'bash ~/jarvis-alpha/scripts/jarvisalpha_pull.sh'"
  $MANUAL_GATEWAY && echo "     Gateway: ssh infranet@100.112.63.25 'bash ~/jarvis-alpha/scripts/jarvisalpha_pull.sh'"
  $MANUAL_ENDPOINT && echo "     Endpoint: ssh jarvisendpoint@100.87.223.31 'bash ~/jarvis-alpha/scripts/jarvisalpha_pull.sh'"
  echo ""
fi
echo -e "${CYAN}─────────────────────────────────────────────────────────${RESET}"
echo ""

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
  echo -e "${GREEN}✅ Sandbox pulled — ${sandbox_short}${RESET}"
  sandbox_footer="pulled ✅ ($sandbox_short)"
  pull_ok=1
else
  echo -e "${RED}❌ Sandbox pull failed${RESET}"
  echo "$pull_output" >&2
  sandbox_footer="pull failed ❌"
fi

# ── Step 8 — SCP dist to Endpoint ────────────────────────
ENDPOINT_HOST="jarvisendpoint@100.87.223.31"
scp_output=$(scp "${SSH_OPTS[@]}" -r "$REPO_DIR/ui/dist" "$ENDPOINT_HOST:~/jarvis-alpha/ui/" 2>&1)
scp_ec=$?
if [[ $scp_ec -eq 0 ]]; then
  echo -e "${GREEN}✅ UI dist → Endpoint${RESET}"
else
  echo -e "${RED}❌ dist scp to Endpoint failed${RESET}"
  echo "$scp_output" >&2
fi

# ── Step 9 — Intel refresh on Sandbox ─────────────────────
if [[ $pull_ok -eq 1 ]]; then
  echo ""
  echo "Triggering intel refresh for jarvis-alpha (project 65)..."
  ssh "${SSH_OPTS[@]}" "$SANDBOX" \
    "curl -sk -X POST 'http://localhost:5001/api/intel/refresh?project_id=65' \
     --max-time 30 | python3 -c \"import sys,json; d=json.load(sys.stdin); r=d.get('results',[{}])[0]; print('Intel:', r.get('symbols','?'), 'symbols' if 'symbols' in r else r.get('error','?'))\"" \
    || echo "Intel refresh skipped"
fi

# ── Step 9 — Footer ───────────────────────────────────────
COMMIT_HASH=$(git -C "$REPO_DIR" rev-parse --short HEAD)
COMMIT_LINE=$(git -C "$REPO_DIR" log -1 --format=%s)
echo ""
echo -e "${CYAN}── ALPHA COMMIT COMPLETE ────────────────────────────────${RESET}"
echo "Commit: $COMMIT_HASH — $COMMIT_LINE"
echo "Air → GitHub ✅"
echo "Sandbox: $sandbox_footer"
echo -e "${CYAN}─────────────────────────────────────────────────────────${RESET}"
