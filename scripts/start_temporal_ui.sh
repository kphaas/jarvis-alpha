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

UI_BIN="$HOME/jarvis/bin/temporal-ui/current/ui-server"

if [[ ! -x "$UI_BIN" ]]; then
  echo "ERROR: ui-server binary not found or not executable at $UI_BIN" >&2
  exit 1
fi

CONFIG_PARENT="$HOME/jarvis-alpha/brain/config"
CONFIG_SUBDIR="temporal-ui"

if [[ ! -f "$CONFIG_PARENT/$CONFIG_SUBDIR/config.yaml" ]]; then
  echo "ERROR: temporal-ui config.yaml not found at $CONFIG_PARENT/$CONFIG_SUBDIR/config.yaml" >&2
  exit 1
fi

# Translate secrets values to TEMPORAL_* env vars that ui-server reads natively
# (see https://docs.temporal.io/references/web-ui-environment-variables).
# YAML-based ${VAR} substitution is NOT supported by ui-server (only temporal-server).
export TEMPORAL_ADDRESS="127.0.0.1:${TEMPORAL_GRPC_PORT}"
export TEMPORAL_UI_PORT="${TEMPORAL_UI_PORT}"
export TEMPORAL_UI_ENABLED=true
export TEMPORAL_DEFAULT_NAMESPACE=default
export TEMPORAL_AUTH_ENABLED=false

# Workaround for ui-server --config flag stripping leading slash from absolute
# paths (ref: github.com/temporalio/temporal issue #6226). Cd into parent dir
# and use a relative subdir path.
cd "$CONFIG_PARENT"

exec "$UI_BIN" --config "$CONFIG_SUBDIR" --env config start
