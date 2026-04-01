#!/bin/bash
set -e

REPO_DIR="$HOME/jarvis-alpha"
SECRETS_FILE="$HOME/jarvis/.secrets"

if [ ! -f "$SECRETS_FILE" ]; then
  echo "ERROR: secrets file not found at $SECRETS_FILE"
  exit 1
fi

set -a
source "$SECRETS_FILE"
set +a

if [ -z "$GITHUB_TOKEN" ]; then
  echo "ERROR: GITHUB_TOKEN not set in secrets"
  exit 1
fi

cd "$REPO_DIR"
git remote set-url origin https://kphaas:${GITHUB_TOKEN}@github.com/kphaas/jarvis-alpha.git
git pull origin main --rebase
echo "jarvis-alpha pull complete: $(git rev-parse --short HEAD)"
