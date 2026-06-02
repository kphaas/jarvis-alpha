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
  porchlight\ jwt-exp\ ALPHA_SERVICE_TOKEN\ *)
    set -- ${SSH_ORIGINAL_COMMAND}
    min_hours="${4:-24}"
    case "$min_hours" in
      ''|*[!0-9.]*)
        echo "invalid jwt min-hours" >&2
        exit 64
        ;;
    esac
    exec python3 - "$min_hours" <<'PY'
import base64
import json
import pathlib
import sys
from datetime import datetime, timezone

min_hours = float(sys.argv[1])
secret_paths = [
    pathlib.Path.home() / "jarvis" / ".secrets",
    pathlib.Path.home() / ".secrets",
]
token = ""
for path in secret_paths:
    if not path.exists():
        continue
    for line in path.read_text().splitlines():
        if line.startswith("ALPHA_SERVICE_TOKEN="):
            token = line.split("=", 1)[1].strip()
            break
    if token:
        break

if not token:
    print(json.dumps({"status": "failed", "detail": "remote JWT secret is not configured"}))
    raise SystemExit(0)

try:
    parts = token.split(".")
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    claims = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
    exp = int(claims["exp"])
    hours = (
        datetime.fromtimestamp(exp, timezone.utc) - datetime.now(timezone.utc)
    ).total_seconds() / 3600
except Exception as exc:
    print(
        json.dumps(
            {
                "status": "failed",
                "detail": "JWT expiration could not be decoded: "
                + exc.__class__.__name__,
            }
        )
    )
    raise SystemExit(0)

if hours <= 0:
    status = "failed"
    detail = "JWT is expired"
elif hours < min_hours:
    status = "warning"
    detail = f"JWT expires in {hours:.1f} hours"
else:
    status = "passed"
    detail = f"JWT expires in {hours:.1f} hours"
print(json.dumps({"status": status, "detail": detail}))
PY
    ;;
  *)
    echo "Porchlight probe command denied" >&2
    exit 126
    ;;
esac
