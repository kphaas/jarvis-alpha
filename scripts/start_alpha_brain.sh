#!/bin/bash
set -e

REPO_DIR="$HOME/jarvis-alpha"
SECRETS_FILE="$HOME/jarvis/.secrets"
VENV="$REPO_DIR/.venv"
CERT_DIR="$HOME/jarvis/certs"
LOG_DIR="$HOME/jarvis-alpha/logs"

mkdir -p "$LOG_DIR"

if [ ! -f "$SECRETS_FILE" ]; then
  echo "ERROR: secrets file not found"
  exit 1
fi

set -a
source "$SECRETS_FILE"
set +a

cd "$REPO_DIR"

find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

exec "$VENV/bin/python3.12" -m uvicorn brain.app:app \
  --host 0.0.0.0 \
  --port 8185 \
  --ssl-certfile "$CERT_DIR/brain.crt" \
  --ssl-keyfile "$CERT_DIR/brain.key" \
  --log-level info
