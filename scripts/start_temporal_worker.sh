#!/usr/bin/env bash
set -euo pipefail

set -a
source ~/jarvis/.secrets
set +a

: "${ALPHA_DB_DSN_WRITER:?ALPHA_DB_DSN_WRITER not set in ~/jarvis/.secrets}"
: "${TEMPORAL_BIND_HOST:?TEMPORAL_BIND_HOST not set in ~/jarvis/.secrets}"
: "${TEMPORAL_GRPC_PORT:?TEMPORAL_GRPC_PORT not set in ~/jarvis/.secrets}"

cd ~/jarvis-alpha
export PYTHONPATH="$(pwd)/common${PYTHONPATH:+:$PYTHONPATH}"

exec .venv/bin/python3.12 -m brain.dream.worker \
  >> ~/jarvis-alpha/logs/temporal_worker.log \
  2>> ~/jarvis-alpha/logs/temporal_worker_error.log
