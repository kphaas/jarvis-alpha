#!/bin/bash
# Start Temporal Server on Brain
# Pattern: source secrets -> render config template -> exec temporal-server
# JARVIS convention: no hardcoded IPs, ports, or secrets

set -euo pipefail

set -a
source ~/jarvis/.secrets
set +a

: "${TEMPORAL_DB_PASSWORD:?TEMPORAL_DB_PASSWORD not set in ~/jarvis/.secrets}"
: "${TEMPORAL_BIND_HOST:?TEMPORAL_BIND_HOST not set in ~/jarvis/.secrets}"
: "${TEMPORAL_GRPC_PORT:?TEMPORAL_GRPC_PORT not set in ~/jarvis/.secrets}"

export TEMPORAL_LOG_LEVEL="${TEMPORAL_LOG_LEVEL:-info}"

TEMPORAL_BIN="$HOME/jarvis/bin/temporal/current/temporal-server"
CONFIG_DIR="$HOME/jarvis-alpha/brain/config/temporal"

if [[ ! -x "$TEMPORAL_BIN" ]]; then
  echo "ERROR: temporal-server binary not found or not executable at $TEMPORAL_BIN" >&2
  exit 1
fi

if [[ ! -f "$CONFIG_DIR/config.yaml" ]]; then
  echo "ERROR: config.yaml not found at $CONFIG_DIR/config.yaml" >&2
  exit 1
fi

exec "$TEMPORAL_BIN" \
  --config-file "$CONFIG_DIR/config.yaml" \
  --allow-no-auth \
  start
