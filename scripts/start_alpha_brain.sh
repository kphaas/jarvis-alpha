#!/usr/bin/env bash
set -a && source ~/jarvis/.secrets && set +a
cd ~/jarvis-alpha
source .venv/bin/activate
find brain -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
python3.12 -m uvicorn brain.app:app \
  --host 0.0.0.0 \
  --port 8186 \
  --ssl-certfile ~/jarvis/certs/brain.crt \
  --ssl-keyfile ~/jarvis/certs/brain.key \
  --log-level info
