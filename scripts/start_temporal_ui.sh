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
CONFIG_DIR="$CONFIG_PARENT/$CONFIG_SUBDIR"
TEMPLATE_FILE="$CONFIG_DIR/config.yaml.template"
RENDERED_FILE="$CONFIG_DIR/config.yaml"

if [[ ! -f "$TEMPLATE_FILE" ]]; then
  echo "ERROR: template not found at $TEMPLATE_FILE" >&2
  exit 1
fi

# Render template -> runtime config.yaml. Replaces ${VAR} with env values.
# macOS-native perl (no envsubst dependency).
perl -pe 's/\$\{([A-Z_][A-Z0-9_]*)\}/defined $ENV{$1} ? $ENV{$1} : $&/ge' \
  < "$TEMPLATE_FILE" > "$RENDERED_FILE"

if [[ ! -s "$RENDERED_FILE" ]]; then
  echo "ERROR: rendered config is empty at $RENDERED_FILE" >&2
  exit 1
fi

# Sanity-check: rendered file must not contain unresolved ${...} placeholders
if grep -q '\${' "$RENDERED_FILE"; then
  echo "ERROR: rendered config still contains unresolved \${...} placeholders" >&2
  grep '\${' "$RENDERED_FILE" >&2
  exit 1
fi

echo "temporal-ui: rendered $TEMPLATE_FILE -> $RENDERED_FILE" >&2

# ui-server requires --config <dir> --env <name> where <name>.yaml exists in <dir>.
# The leading-slash stripping bug (GitHub issue #6226) requires cd + relative path.
cd "$CONFIG_PARENT"
exec "$UI_BIN" --config "$CONFIG_SUBDIR" --env config start
