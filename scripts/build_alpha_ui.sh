#!/bin/bash
# Build the Alpha UI with the production Brain URL baked into the Vite bundle.
# Vite replaces import.meta.env at build time; missing VITE_BRAIN_URL ships a
# broken bundle that calls undefined/v1/... from the browser.

set -euo pipefail

REPO_DIR="${JARVIS_ALPHA_REPO_DIR:-${HOME}/jarvis-alpha}"
UI_DIR="${REPO_DIR}/ui"
DEFAULT_BRAIN_URL="https://jarvis-brain.tail40ed36.ts.net:8186"
BRAIN_URL="${VITE_BRAIN_URL:-${JARVIS_ALPHA_UI_BRAIN_URL:-$DEFAULT_BRAIN_URL}}"
DEFAULT_ALPHA_UI_URL="https://jarvis-endpoint.tail40ed36.ts.net:4100"
DEFAULT_FAMILY_UI_URL="https://jarvis-endpoint.tail40ed36.ts.net:4200"
DEFAULT_FORGE_UI_URL="https://jarvis-forge.tail40ed36.ts.net:5001"
ALPHA_UI_URL="${VITE_ALPHA_UI_URL:-${JARVIS_ALPHA_UI_URL:-$DEFAULT_ALPHA_UI_URL}}"
FAMILY_UI_URL="${VITE_FAMILY_UI_URL:-${JARVIS_FAMILY_UI_URL:-$DEFAULT_FAMILY_UI_URL}}"
FORGE_UI_URL="${VITE_FORGE_UI_URL:-${JARVIS_FORGE_UI_URL:-$DEFAULT_FORGE_UI_URL}}"

if [ -z "$BRAIN_URL" ]; then
  echo "ERROR: VITE_BRAIN_URL resolved empty; refusing to build Alpha UI" >&2
  exit 1
fi

validate_url() {
  local name="$1"
  local value="$2"

  if [ -z "$value" ]; then
    echo "ERROR: $name resolved empty; refusing to build Alpha UI" >&2
    exit 1
  fi

  case "$value" in
  http://*|https://*) ;;
  *)
    echo "ERROR: $name must be an absolute http(s) URL: $value" >&2
    exit 1
    ;;
  esac
}

validate_url "VITE_BRAIN_URL" "$BRAIN_URL"
validate_url "VITE_ALPHA_UI_URL" "$ALPHA_UI_URL"
validate_url "VITE_FAMILY_UI_URL" "$FAMILY_UI_URL"
validate_url "VITE_FORGE_UI_URL" "$FORGE_UI_URL"

export VITE_BRAIN_URL="$BRAIN_URL"
export VITE_ALPHA_UI_URL="$ALPHA_UI_URL"
export VITE_FAMILY_UI_URL="$FAMILY_UI_URL"
export VITE_FORGE_UI_URL="$FORGE_UI_URL"

cd "$UI_DIR"
npm run build --silent

if grep -R -qE 'undefined/v1/|VITE_BRAIN_URL not set' dist/assets dist/index.html; then
  echo "ERROR: built Alpha UI still contains an unresolved Brain URL" >&2
  exit 1
fi

if grep -R -qE 'eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}' dist/assets dist/index.html; then
  echo "ERROR: built Alpha UI appears to contain a JWT-shaped token" >&2
  exit 1
fi

if ! grep -R -qF "$BRAIN_URL" dist/assets dist/index.html; then
  echo "ERROR: built Alpha UI does not contain expected Brain URL: $BRAIN_URL" >&2
  exit 1
fi

for expected_url in "$ALPHA_UI_URL" "$FAMILY_UI_URL" "$FORGE_UI_URL"; do
  if ! grep -R -qF "$expected_url" dist/assets dist/index.html; then
    echo "ERROR: built Alpha UI does not contain expected space launch URL: $expected_url" >&2
    exit 1
  fi
done

echo "Alpha UI built with VITE_BRAIN_URL=$BRAIN_URL"
echo "Alpha UI space links: VITE_ALPHA_UI_URL=$ALPHA_UI_URL VITE_FAMILY_UI_URL=$FAMILY_UI_URL VITE_FORGE_UI_URL=$FORGE_UI_URL"
