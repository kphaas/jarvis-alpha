#!/usr/bin/env bash
# Non-live canary for Spark approved-send production readiness.
# It checks metadata/readiness only. It never calls the approved-send endpoint.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

BASE_URL="${ALPHA_BASE_URL:-https://jarvis-brain.tail40ed36.ts.net:8186}"
TIMEOUT_SEC="${SPARK_SMOKE_TIMEOUT_SEC:-15}"
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
      --scopes "spark.draft,imessage.read,admin" \
      --days 1 2>/dev/null || true
  )"
fi

if [ -z "${TOKEN}" ]; then
  echo "SKIP: set SPARK_SMOKE_TOKEN or run on a node with a service private key." >&2
  exit 2
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

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
forbidden_keys = {
    "password",
    "chat_guid",
    "chatGuid",
    "phone_number",
    "display_name",
    "draft_text",
}
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

if label == "readiness":
    ready = payload.get("ready")
    checks = payload.get("checks")
    if ready is not True:
        raise SystemExit("FAIL readiness: ready was not true")
    if not isinstance(checks, list) or not checks:
        raise SystemExit("FAIL readiness: checks missing")
    failed = [check for check in checks if check.get("status") != "passed"]
    if failed:
        raise SystemExit(f"FAIL readiness: {len(failed)} check(s) not passed")
    if payload.get("body_access") is not False:
        raise SystemExit("FAIL readiness: body_access was not false")
    print(f"PASS readiness: ready=true checks={len(checks)}")
elif label == "targets":
    targets = payload.get("targets")
    if not isinstance(targets, list) or not targets:
        raise SystemExit("FAIL targets: no approved iMessage target")
    approved_parent_minor = [
        target
        for target in targets
        if target.get("parent_minor_context_approved") is True
    ]
    if not approved_parent_minor:
        raise SystemExit("FAIL targets: no parent-minor approved target")
    print(
        "PASS targets: "
        f"count={len(targets)} parent_minor={len(approved_parent_minor)}"
    )
elif label == "outbox":
    items = payload.get("items")
    if not isinstance(items, list):
        raise SystemExit("FAIL outbox: items missing")
    sent_once = [
        item
        for item in items
        if item.get("status") == "sent"
        and item.get("send_attempt_count") == 1
        and isinstance(item.get("sent_at"), str)
    ]
    if not sent_once:
        raise SystemExit("FAIL outbox: no sent approved item with one attempt")
    stuck = [item for item in items if item.get("status") == "sending"]
    if stuck:
        raise SystemExit("FAIL outbox: send in progress/stuck")
    for item in items:
        if item.get("status") == "sent" and item.get("send_attempt_count") != 1:
            raise SystemExit("FAIL outbox: sent item did not have exactly one attempt")
    print(
        "PASS outbox: "
        f"items={len(items)} sent_once={len(sent_once)} stuck=0"
    )
elif label == "approvals":
    pending = payload.get("pending")
    if not isinstance(pending, list):
        raise SystemExit("FAIL approvals: pending list missing")
    spark_pending = [item for item in pending if item.get("spark") is not None]
    if spark_pending:
        raise SystemExit(
            f"FAIL approvals: {len(spark_pending)} pending Spark approval(s)"
        )
    print(f"PASS approvals: total_pending={len(pending)} spark_pending=0")
else:
    raise SystemExit(f"FAIL unknown label: {label}")
PY
}

get_json "readiness" "/v1/spark/imessage/readiness"
get_json "targets" "/v1/spark/drafts/imessage/targets?principal_id=ken"
get_json "outbox" "/v1/spark/drafts/imessage/outbox?principal_id=ken&limit=25"
get_json "approvals" "/v1/approvals/pending"

echo "PASS spark-send-readiness canary: no live send attempted"
