#!/bin/bash
# Shared node endpoints for jarvis-alpha shell scripts.
#
# App code uses brain/config/node_addresses.py. Shell scripts source this file,
# which reads scripts/node_ssh_map.json so deploy/restart scripts do not carry
# their own stale host/user copies.

if [[ -n "${JARVIS_ALPHA_NODE_ADDRESSES_LOADED:-}" ]]; then
  return 0 2>/dev/null || exit 0
fi
JARVIS_ALPHA_NODE_ADDRESSES_LOADED=1

_jalpha_lib_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
JARVIS_ALPHA_REPO_DIR="${JARVIS_ALPHA_REPO_DIR:-$(cd "${_jalpha_lib_dir}/../.." && pwd)}"
JARVIS_ALPHA_NODE_MAP="${JARVIS_ALPHA_NODE_MAP:-${JARVIS_ALPHA_REPO_DIR}/scripts/node_ssh_map.json}"

_jalpha_node_field() {
  local node="$1"
  local field="$2"
  python3 - "$JARVIS_ALPHA_NODE_MAP" "$node" "$field" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
node = sys.argv[2]
field = sys.argv[3]

data = json.loads(path.read_text(encoding="utf-8"))
try:
    value = data[node][field]
except KeyError:
    print(f"missing {node}.{field} in {path}", file=sys.stderr)
    sys.exit(2)

print(value)
PY
}

export JARVIS_ALPHA_BRAIN_SSH="${JARVIS_ALPHA_BRAIN_SSH:-$(_jalpha_node_field brain ssh_target)}"
export JARVIS_ALPHA_GATEWAY_SSH="${JARVIS_ALPHA_GATEWAY_SSH:-$(_jalpha_node_field gateway ssh_target)}"
export JARVIS_ALPHA_ENDPOINT_SSH="${JARVIS_ALPHA_ENDPOINT_SSH:-$(_jalpha_node_field endpoint ssh_target)}"
export JARVIS_ALPHA_SANDBOX_SSH="${JARVIS_ALPHA_SANDBOX_SSH:-$(_jalpha_node_field sandbox ssh_target)}"

export JARVIS_ALPHA_BRAIN_HEALTH_URL="${JARVIS_ALPHA_BRAIN_HEALTH_URL:-$(_jalpha_node_field brain health_url)}"
export JARVIS_ALPHA_GATEWAY_HEALTH_URL="${JARVIS_ALPHA_GATEWAY_HEALTH_URL:-$(_jalpha_node_field gateway health_url)}"
export JARVIS_ALPHA_ENDPOINT_HEALTH_URL="${JARVIS_ALPHA_ENDPOINT_HEALTH_URL:-$(_jalpha_node_field endpoint health_url)}"
export JARVIS_ALPHA_SANDBOX_HEALTH_URL="${JARVIS_ALPHA_SANDBOX_HEALTH_URL:-$(_jalpha_node_field sandbox health_url)}"
