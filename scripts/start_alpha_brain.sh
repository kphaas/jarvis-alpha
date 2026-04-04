#!/usr/bin/env bash
set -a && source ~/jarvis/.secrets && set +a
cd ~/jarvis-alpha
source .venv/bin/activate
find brain -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
python3.12 - <<'PY'
import os

import uvicorn

from brain.config.uvicorn_log_config import UVICORN_LOG_CONFIG

uvicorn.run(
    "brain.app:app",
    host="0.0.0.0",
    port=8186,
    ssl_certfile=os.path.expanduser("~/jarvis/certs/brain.crt"),
    ssl_keyfile=os.path.expanduser("~/jarvis/certs/brain.key"),
    log_level="info",
    log_config=UVICORN_LOG_CONFIG,
)
PY
