#!/usr/bin/env bash
set -a && source ~/jarvis/.secrets && set +a
cd ~/jarvis-alpha
export PYTHONPATH="$(pwd)/common${PYTHONPATH:+:$PYTHONPATH}"
source .venv/bin/activate
find gateway -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
python3.12 -m uvicorn gateway.app:app \
  --host 0.0.0.0 \
  --port 8283 \
  --ssl-certfile ~/jarvis/certs/gateway.crt \
  --ssl-keyfile ~/jarvis/certs/gateway.key \
  --log-level info
