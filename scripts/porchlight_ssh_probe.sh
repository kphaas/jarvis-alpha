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
  "porchlight restore-drill-status")
    exec python3 - <<'PY'
import glob
import json
import os
from datetime import datetime, timezone

paths = sorted(
    glob.glob(os.path.expanduser("~/jarvis/logs/restore_drill_*.json")),
    key=os.path.getmtime,
    reverse=True,
)
if not paths:
    print(json.dumps({"status": "unavailable", "reason": "no_restore_drill_report"}))
    raise SystemExit(0)

path = paths[0]
with open(path, encoding="utf-8") as handle:
    report = json.load(handle)

run_id = str(report.get("run_id") or "")
notify = {"event": "unknown", "http_code": "", "reason": ""}
log_path = os.path.expanduser("~/jarvis/logs/restore_drill.log")
if run_id and os.path.exists(log_path):
    with open(log_path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if f'"run_id":"{run_id}"' not in line or '"event":"mm_notify_' not in line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            notify = {
                "event": str(event.get("event") or "unknown"),
                "http_code": str(event.get("http_code") or ""),
                "reason": str(event.get("reason") or ""),
            }

mtime = datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc)
payload = {
    "path": path,
    "report_mtime": mtime.isoformat(),
    "run_id": run_id,
    "status": str(report.get("status") or "unknown"),
    "source_dump": str(report.get("source_dump") or ""),
    "restore_rc": report.get("restore_rc"),
    "restore_err_count": report.get("restore_err_count"),
    "pgaudit_err_count": report.get("pgaudit_err_count"),
    "table_count": report.get("table_count"),
    "ref_table_count": report.get("ref_table_count"),
    "fail_reasons": str(report.get("fail_reasons") or ""),
    "notification": notify,
}
print(json.dumps(payload, sort_keys=True))
PY
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
