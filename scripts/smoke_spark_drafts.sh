#!/usr/bin/env bash
# Smoke Spark iMessage draft review endpoints without printing secrets or payloads.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

BASE_URL="${ALPHA_BASE_URL:-https://jarvis-brain.tail40ed36.ts.net:8186}"
TIMEOUT_SEC="${SPARK_SMOKE_TIMEOUT_SEC:-20}"
TOKEN="${SPARK_SMOKE_TOKEN:-${ALPHA_SERVICE_TOKEN:-}}"
ALLOW_UNCONFIGURED="${SPARK_DRAFT_SMOKE_ALLOW_UNCONFIGURED:-false}"
QUEUE_APPROVAL="${SPARK_DRAFT_SMOKE_QUEUE_APPROVAL:-false}"
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
      --scopes "spark.draft,imessage.read" \
      --days 1 2>/dev/null || true
  )"
fi

if [ -z "${TOKEN}" ]; then
  echo "SKIP: set SPARK_SMOKE_TOKEN or run on a node with a service private key." >&2
  exit 2
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

post_json() {
  local label="$1"
  local path="$2"
  local request_path="$3"
  local output_path="${TMP_DIR}/${label}.json"
  local http_code

  if ! http_code="$(
    curl -skS \
      --max-time "${TIMEOUT_SEC}" \
      -o "${output_path}" \
      -w "%{http_code}" \
      -H "Authorization: Bearer ${TOKEN}" \
      -H "Content-Type: application/json" \
      --data-binary "@${request_path}" \
      "${BASE_URL}${path}"
  )"; then
    echo "FAIL ${label}: request failed" >&2
    exit 1
  fi

  "${PYTHON_BIN}" - "${label}" "${output_path}" "${http_code}" "${ALLOW_UNCONFIGURED}" <<'PY'
import json
import sys
from pathlib import Path

label = sys.argv[1]
payload_path = Path(sys.argv[2])
http_code = sys.argv[3]
allow_unconfigured = sys.argv[4].lower() == "true"

if http_code == "503" and allow_unconfigured:
    print(f"SKIP {label}: approved thread runtime config unavailable")
    raise SystemExit(0)
if http_code != "200":
    raise SystemExit(f"FAIL {label}: HTTP {http_code}")

payload = json.loads(payload_path.read_text(encoding="utf-8"))
forbidden_keys = {"password", "chat_guid", "chatGuid", "phone_number", "display_name"}
forbidden_values = ("private inbound body",)


def check_no_forbidden_leaks(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in forbidden_keys:
                raise SystemExit(f"FAIL {label}: forbidden field leaked: {key}")
            check_no_forbidden_leaks(item)
    elif isinstance(value, list):
        for item in value:
            check_no_forbidden_leaks(item)
    elif isinstance(value, str):
        lowered = value.lower()
        for forbidden in forbidden_values:
            if forbidden in lowered:
                raise SystemExit(f"FAIL {label}: forbidden value leaked: {forbidden}")


check_no_forbidden_leaks(payload)

if payload.get("can_send") is not False:
    raise SystemExit(f"FAIL {label}: can_send was not false")
if payload.get("requires_human_approval") is not True:
    raise SystemExit(f"FAIL {label}: human approval was not required")
if payload.get("durable_storage_allowed") is not False:
    raise SystemExit(f"FAIL {label}: durable storage was not false")
if not isinstance(payload.get("draft_text"), str) or not payload["draft_text"].strip():
    raise SystemExit(f"FAIL {label}: draft_text missing")

if label == "approval":
    if not payload.get("queue_id"):
        raise SystemExit("FAIL approval: queue_id missing")
    print("PASS approval: spark draft approval queued")
else:
    print(
        "PASS draft: "
        f"context={payload.get('context_messages_read')} "
        f"sent={payload.get('principal_sent_messages')} "
        f"runtime={payload.get('runtime_context_messages')}"
    )
PY
}

get_json() {
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

  "${PYTHON_BIN}" - "${label}" "${output_path}" "${http_code}" "${ALLOW_UNCONFIGURED}" <<'PY'
import json
import sys
from pathlib import Path

label = sys.argv[1]
payload_path = Path(sys.argv[2])
http_code = sys.argv[3]
allow_unconfigured = sys.argv[4].lower() == "true"

if http_code == "503" and allow_unconfigured:
    print(f"SKIP {label}: approved thread runtime config unavailable")
    raise SystemExit(0)
if http_code != "200":
    raise SystemExit(f"FAIL {label}: HTTP {http_code}")

payload = json.loads(payload_path.read_text(encoding="utf-8"))
forbidden_keys = {"password", "chat_guid", "chatGuid", "phone_number", "display_name"}
forbidden_values = ("private inbound body",)


def check_no_forbidden_leaks(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in forbidden_keys:
                raise SystemExit(f"FAIL {label}: forbidden field leaked: {key}")
            check_no_forbidden_leaks(item)
    elif isinstance(value, list):
        for item in value:
            check_no_forbidden_leaks(item)
    elif isinstance(value, str):
        lowered = value.lower()
        for forbidden in forbidden_values:
            if forbidden in lowered:
                raise SystemExit(f"FAIL {label}: forbidden value leaked: {forbidden}")


check_no_forbidden_leaks(payload)

if label == "targets":
    targets = payload.get("targets")
    if not isinstance(targets, list):
        raise SystemExit("FAIL targets: targets missing")
    print(f"PASS targets: count={len(targets)}")
elif label == "target_preview":
    context_preview = payload.get("context_preview")
    if not isinstance(context_preview, list):
        raise SystemExit("FAIL target_preview: context_preview missing")
    if len(context_preview) > 8:
        raise SystemExit("FAIL target_preview: more than 8 messages returned")
    if payload.get("durable_storage_allowed") is not False:
        raise SystemExit("FAIL target_preview: durable storage was not false")
    print(f"PASS target-preview: context={len(context_preview)}")
else:
    print(f"PASS {label}: reachable")
PY
}

REQUEST_JSON="${TMP_DIR}/draft_request.json"
"${PYTHON_BIN}" - "${REQUEST_JSON}" <<'PY'
import json
import sys
from pathlib import Path

Path(sys.argv[1]).write_text(
    json.dumps(
        {
            "principal_id": "ken",
            "reply_goal": "Smoke-check the Spark draft review path.",
            "max_context_messages": 5,
        },
        separators=(",", ":"),
    ),
    encoding="utf-8",
)
PY

TARGETS_PATH="/v1/spark/drafts/imessage/targets?principal_id=ken"
get_json "targets" "${TARGETS_PATH}"

TARGET_PREVIEW_PATH="$(
  "${PYTHON_BIN}" - "${TMP_DIR}/targets.json" <<'PY'
import json
import sys
from pathlib import Path
from urllib.parse import quote

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
targets = payload.get("targets") or []
if not targets:
    raise SystemExit(0)
approval_id = str(targets[0].get("approval_id") or "")
if not approval_id:
    raise SystemExit(0)
print(
    "/v1/spark/drafts/imessage/target-preview"
    f"?principal_id=ken&approval_id={quote(approval_id, safe='')}&limit=8"
)
PY
)"

if [ -n "${TARGET_PREVIEW_PATH}" ]; then
  get_json "target_preview" "${TARGET_PREVIEW_PATH}"
else
  echo "SKIP target-preview: no approved iMessage target"
fi

post_json "draft" "/v1/spark/drafts/imessage" "${REQUEST_JSON}"

if [ "${QUEUE_APPROVAL}" = "true" ]; then
  APPROVAL_JSON="${TMP_DIR}/approval_request.json"
  "${PYTHON_BIN}" - "${APPROVAL_JSON}" <<'PY'
import json
import sys
from pathlib import Path

Path(sys.argv[1]).write_text(
    json.dumps(
        {
            "principal_id": "ken",
            "reply_goal": "Smoke-check the Spark approval path.",
            "max_context_messages": 5,
            "draft_text_override": "Smoke-check draft for approval.",
        },
        separators=(",", ":"),
    ),
    encoding="utf-8",
)
PY
  post_json "approval" "/v1/spark/drafts/imessage/approval-request" "${APPROVAL_JSON}"
fi

echo "PASS spark-drafts smoke: draft review surface is reachable"
