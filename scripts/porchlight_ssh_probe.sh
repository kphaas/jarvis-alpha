#!/bin/sh
# Restricted SSH command target for Porchlight node health probes.

set -eu

case "${SSH_ORIGINAL_COMMAND:-}" in
  "launchctl list")
    exec launchctl list
    ;;
  'tail -n 120 "$HOME/jarvis-alpha/logs/token_rotation.log" 2>/dev/null || true')
    exec /bin/sh -lc 'tail -n 120 "$HOME/jarvis-alpha/logs/token_rotation.log" 2>/dev/null || true'
    ;;
  *)
    echo "Porchlight probe command denied" >&2
    exit 126
    ;;
esac
