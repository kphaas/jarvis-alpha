#!/usr/bin/env bash
# Smoke the Spark iMessage read-only facade without printing secrets or payloads.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

BASE_URL="${ALPHA_BASE_URL:-https://jarvis-brain.tail40ed36.ts.net:8186}"
TIMEOUT_SEC="${SPARK_SMOKE_TIMEOUT_SEC:-10}"
TOKEN="${SPARK_SMOKE_TOKEN:-${ALPHA_SERVICE_TOKEN:-}}"
if [ -x "${REPO_ROOT}/.venv/bin/python" ]; then
  DEFAULT_PYTHON="${REPO_ROOT}/.venv/bin/python"
else
  DEFAULT_PYTHON="python3"
fi
PYTHON_BIN="${SPARK_SMOKE_PYTHON:-${DEFAULT_PYTHON}}"

if [ -z "${TOKEN}" ] && [ -f "${HOME}/jarvis/.secrets" ]; then
  set +u
  # shellcheck disable=SC1090
  source "${HOME}/jarvis/.secrets"
  set -u
  TOKEN="${SPARK_SMOKE_TOKEN:-${ALPHA_SERVICE_TOKEN:-}}"
fi

if [ -z "${TOKEN}" ]; then
  SMOKE_ISS="${SPARK_SMOKE_ISS:-brain}"
  TOKEN="$(
    "${PYTHON_BIN}" "${REPO_ROOT}/scripts/gen_service_token.py" \
      --iss "${SMOKE_ISS}" \
      --actor-type service \
      --scopes "imessage.read" \
      --days 1 2>/dev/null || true
  )"
fi

if [ -z "${TOKEN}" ]; then
  echo "SKIP: set SPARK_SMOKE_TOKEN or run on a node with a service private key." >&2
  exit 2
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

curl_json() {
  local label="$1"
  local path="$2"
  local output_path="${TMP_DIR}/${label}.json"
  local http_code

  if ! http_code="$(
    curl -skS \
      --max-time "${TIMEOUT_SEC}" \
      -o "${output_path}" \
      -w "%{http_code}" \
      -H "Authorization: Bearer ${TOKEN}" \
      "${BASE_URL}${path}"
  )"; then
    echo "FAIL ${label}: request failed" >&2
    exit 1
  fi

  "${PYTHON_BIN}" - "${label}" "${output_path}" "${http_code}" <<'PY'
import json
import sys
from pathlib import Path

label = sys.argv[1]
payload_path = Path(sys.argv[2])
http_code = sys.argv[3]

if http_code != "200":
    raise SystemExit(f"FAIL {label}: HTTP {http_code}")

payload = json.loads(payload_path.read_text(encoding="utf-8"))
if payload.get("body_access") is not False:
    raise SystemExit(f"FAIL {label}: body_access was not false")

serialized = json.dumps(payload, sort_keys=True).lower()
for forbidden in ("password", "chat_guid", "display_name", "phone_number"):
    if forbidden in serialized:
        raise SystemExit(f"FAIL {label}: forbidden field leaked: {forbidden}")

if label == "health":
    print(
        "PASS health: "
        f"body_access=false private_api={payload.get('private_api')} "
        f"helper_connected={payload.get('helper_connected')}"
    )
elif label == "counts":
    for field in (
        "total_chats",
        "imessage_chats",
        "sms_chats",
        "rcs_chats",
        "sent_messages",
    ):
        if not isinstance(payload.get(field), int):
            raise SystemExit(f"FAIL counts: {field} is not an int")
    print(
        "PASS counts: "
        f"body_access=false total_chats={payload['total_chats']} "
        f"sent_messages={payload['sent_messages']}"
    )
elif label == "metadata":
    if "data" in payload:
        raise SystemExit("FAIL metadata: raw data array was returned")
    for field in ("count", "total", "offset", "limit", "data_count"):
        if not isinstance(payload.get(field), int):
            raise SystemExit(f"FAIL metadata: {field} is not an int")
    print(
        "PASS metadata: "
        f"body_access=false data_count={payload['data_count']} "
        f"total={payload['total']}"
    )
else:
    raise SystemExit(f"FAIL unknown label: {label}")
PY
}

curl_json "health" "/v1/spark/imessage/health"
curl_json "counts" "/v1/spark/imessage/counts"
curl_json "metadata" "/v1/spark/imessage/recent-chats/metadata?limit=5&offset=0"

echo "PASS spark-imessage smoke: read-only facade is reachable"
