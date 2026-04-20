#!/bin/bash
# Start Temporal UI Server on Brain
# Pattern: source secrets -> export TEMPORAL_* env vars -> exec ui-server
# UI config: YAML in brain/config/temporal-ui/ with ${VAR} from env (secrets)

set -euo pipefail

set -a
source ~/jarvis/.secrets
set +a

: "${TEMPORAL_BIND_HOST:?TEMPORAL_BIND_HOST not set in ~/jarvis/.secrets}"
: "${TEMPORAL_GRPC_PORT:?TEMPORAL_GRPC_PORT not set in ~/jarvis/.secrets}"
: "${TEMPORAL_UI_PORT:?TEMPORAL_UI_PORT not set in ~/jarvis/.secrets}"

export TEMPORAL_ADDRESS="${TEMPORAL_BIND_HOST}:${TEMPORAL_GRPC_PORT}"
export TEMPORAL_UI_PORT="${TEMPORAL_UI_PORT}"
export TEMPORAL_UI_PUBLIC_PATH=""
export TEMPORAL_DEFAULT_NAMESPACE="default"

UI_BIN="$HOME/jarvis/bin/temporal-ui/current/ui-server"

if [[ ! -x "$UI_BIN" ]]; then
  echo "ERROR: ui-server binary not found or not executable at $UI_BIN" >&2
  exit 1
fi

CONFIG_DIR="$HOME/jarvis-alpha/brain/config/temporal-ui"
if [[ ! -f "$CONFIG_DIR/config.yaml" ]]; then
  echo "ERROR: temporal-ui config.yaml not found at $CONFIG_DIR/config.yaml" >&2
  exit 1
fi

exec "$UI_BIN" --config "$CONFIG_DIR" --env config start
