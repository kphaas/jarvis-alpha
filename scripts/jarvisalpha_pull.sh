#!/bin/bash
set -uo pipefail

REPO_DIR="${HOME}/jarvis-alpha"
SECRETS_FILE="${HOME}/jarvis/.secrets"

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
