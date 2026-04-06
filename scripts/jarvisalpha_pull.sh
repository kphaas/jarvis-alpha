#!/bin/bash
set -uo pipefail

REPO_DIR="${HOME}/jarvis-alpha"
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
  git clone https://kphaas:${GITHUB_TOKEN}@github.com/kphaas/jarvis-alpha.git "$REPO_DIR"
else
  cd "$REPO_DIR"
  git config credential.helper ""
  GIT_TERMINAL_PROMPT=0 git remote set-url origin https://kphaas:${GITHUB_TOKEN}@github.com/kphaas/jarvis-alpha.git
  GIT_TERMINAL_PROMPT=0 git pull origin main --rebase
fi

SHORT=$(git -C "$REPO_DIR" rev-parse --short HEAD)
echo ""
echo "✅ jarvis-alpha pulled — $SHORT"
echo "─────────────────────────────────────────────────────────"

BRAIN_PLIST="${HOME}/Library/LaunchAgents/com.jarvis.alpha.brain.plist"
if [ -f "$BRAIN_PLIST" ]; then
  echo ""
  echo "Restarting Alpha Brain LaunchAgent..."
  launchctl unload "$BRAIN_PLIST" 2>/dev/null || true
  sleep 1
  lsof -ti :8186 | xargs kill -9 2>/dev/null || true
  sleep 2
  find "${REPO_DIR}/brain" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
  launchctl load "$BRAIN_PLIST"
  sleep 4
  if curl -sk --max-time 5 https://jarvis-brain.tail40ed36.ts.net:8186/health | grep -q '"status":"ok"'; then
    echo "✅ Alpha Brain healthy after restart"
  else
    echo "⚠️  Alpha Brain health check failed — check logs"
    tail -5 "${REPO_DIR}/logs/alpha_brain_error.log" 2>/dev/null
  fi

  echo ""
  echo "Restarting Buddy Agent..."
  launchctl unload ~/Library/LaunchAgents/com.jarvis.alpha.buddy.plist 2>/dev/null
  sleep 1
  launchctl load ~/Library/LaunchAgents/com.jarvis.alpha.buddy.plist
  echo "✅ Buddy agent restarted"
fi
