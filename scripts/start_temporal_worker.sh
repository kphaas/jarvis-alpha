#!/usr/bin/env bash
set -euo pipefail

set -a
source ~/jarvis/.secrets
set +a

: "${ALPHA_DB_DSN_WRITER:?ALPHA_DB_DSN_WRITER not set in ~/jarvis/.secrets}"

# Temporal server binds loopback-only on Brain. The local worker should connect
# over loopback even if server-side bind/advertise settings point at Tailscale.
export TEMPORAL_BIND_HOST="${TEMPORAL_WORKER_BIND_HOST:-127.0.0.1}"
export TEMPORAL_GRPC_PORT="${TEMPORAL_WORKER_GRPC_PORT:-${TEMPORAL_GRPC_PORT:-7233}}"
: "${TEMPORAL_GRPC_PORT:?TEMPORAL_GRPC_PORT not set}"

cd ~/jarvis-alpha
export PYTHONPATH="$(pwd)/common${PYTHONPATH:+:$PYTHONPATH}"

exec .venv/bin/python3.12 -m brain.dream.worker \
  >> ~/jarvis-alpha/logs/temporal_worker.log \
  2>> ~/jarvis-alpha/logs/temporal_worker_error.log
