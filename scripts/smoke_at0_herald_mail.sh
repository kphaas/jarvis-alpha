#!/usr/bin/env bash
# Smoke AT-0 Herald mail intake without printing message content or secrets.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

BASE_URL="${ALPHA_BASE_URL:-https://jarvis-brain.tail40ed36.ts.net:8186}"
TIMEOUT_SEC="${HERALD_SMOKE_TIMEOUT_SEC:-30}"
MAX_RESULTS="${HERALD_SMOKE_MAX_RESULTS:-1}"
TOKEN="${HERALD_SMOKE_TOKEN:-${ALPHA_SERVICE_TOKEN:-}}"
SEND_DRAFT_ID="${HERALD_SMOKE_SEND_DRAFT_ID:-}"
if [ -x "${REPO_ROOT}/.venv/bin/python" ]; then
  DEFAULT_PYTHON="${REPO_ROOT}/.venv/bin/python"
else
  DEFAULT_PYTHON="python3"
fi
PYTHON_BIN="${HERALD_SMOKE_PYTHON:-${DEFAULT_PYTHON}}"

if [ -z "${TOKEN}" ] && [ -f "${HOME}/jarvis/.secrets" ]; then
  set +u
  # shellcheck disable=SC1090
  source "${HOME}/jarvis/.secrets"
  set -u
  TOKEN="${HERALD_SMOKE_TOKEN:-${ALPHA_SERVICE_TOKEN:-}}"
fi

if [ -z "${TOKEN}" ]; then
  SMOKE_ISS="${HERALD_SMOKE_ISS:-brain}"
  TOKEN="$(
    "${PYTHON_BIN}" "${REPO_ROOT}/scripts/gen_service_token.py" \
      --iss "${SMOKE_ISS}" \
      --actor-type service \
      --scopes "herald.read,herald.write,at0_mail.read,at0_mail.scan,at0_mail.write" \
      --days 1 2>/dev/null || true
  )"
fi

if [ -z "${TOKEN}" ]; then
  echo "SKIP: set HERALD_SMOKE_TOKEN or run on a node with a service private key." >&2
  exit 2
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

request_json() {
  local method="$1"
  local label="$2"
  local path="$3"
  local output_path="${TMP_DIR}/${label}.json"
  local http_code

  if ! http_code="$(
    curl -skS \
      --max-time "${TIMEOUT_SEC}" \
      -o "${output_path}" \
      -w "%{http_code}" \
      -X "${method}" \
      -H "Authorization: Bearer ${TOKEN}" \
      -H "Accept: application/json" \
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
    "access_token",
    "client_assertion",
    "private_key",
    "certificate",
    "password",
}


def check_forbidden_keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in forbidden_keys:
                raise SystemExit(f"FAIL {label}: forbidden field leaked: {key}")
            check_forbidden_keys(item)
    elif isinstance(value, list):
        for item in value:
            check_forbidden_keys(item)


check_forbidden_keys(payload)

if label == "scan":
    for field in (
        "mailboxes_scanned",
        "messages_seen",
        "messages_new",
        "draft_proposals_created",
    ):
        if not isinstance(payload.get(field), int):
            raise SystemExit(f"FAIL scan: {field} is not an int")
    print(
        "PASS scan: "
        f"mailboxes={payload['mailboxes_scanned']} "
        f"seen={payload['messages_seen']} "
        f"new={payload['messages_new']} "
        f"drafts={payload['draft_proposals_created']}"
    )
elif label == "health":
    if payload.get("status") not in {"ok", "running"}:
        raise SystemExit(f"FAIL health: status={payload.get('status')}")
    if payload.get("requires_attention") is not False:
        raise SystemExit("FAIL health: requires_attention was not false")
    if not isinstance(payload.get("stale_after_minutes"), int):
        raise SystemExit("FAIL health: stale_after_minutes missing")
    print(
        "PASS health: "
        f"status={payload['status']} "
        f"age_minutes={payload.get('age_minutes')}"
    )
elif label == "mailboxes":
    if not isinstance(payload.get("mailboxes"), list):
        raise SystemExit("FAIL mailboxes: mailboxes missing")
    if not payload["mailboxes"]:
        raise SystemExit("FAIL mailboxes: no configured mailboxes returned")
    print(f"PASS mailboxes: count={len(payload['mailboxes'])}")
elif label == "spark":
    if payload.get("spark_id") != "at0-spark":
        raise SystemExit(f"FAIL spark: unexpected spark_id={payload.get('spark_id')}")
    if payload.get("can_send") is not False:
        raise SystemExit("FAIL spark: can_send was not false")
    if payload.get("requires_human_approval") is not True:
        raise SystemExit("FAIL spark: requires_human_approval was not true")
    print(f"PASS spark: profile={payload['spark_id']} draft_only=true")
elif label == "dashboard":
    for field in ("message_counts", "draft_counts"):
        if not isinstance(payload.get(field), list):
            raise SystemExit(f"FAIL dashboard: {field} missing")
    print(
        "PASS dashboard: "
        f"message_groups={len(payload['message_counts'])} "
        f"draft_groups={len(payload['draft_counts'])}"
    )
elif label == "messages":
    if not isinstance(payload.get("messages"), list):
        raise SystemExit("FAIL messages: messages missing")
    print(f"PASS messages: count={len(payload['messages'])}")
elif label == "drafts":
    if not isinstance(payload.get("drafts"), list):
        raise SystemExit("FAIL drafts: drafts missing")
    print(f"PASS drafts: count={len(payload['drafts'])}")
elif label == "send":
    if payload.get("status") != "sent":
        raise SystemExit(f"FAIL send: status={payload.get('status')}")
    if payload.get("graph_status_code") != 202:
        raise SystemExit(f"FAIL send: graph_status_code={payload.get('graph_status_code')}")
    if not isinstance(payload.get("send_attempt_count"), int):
        raise SystemExit("FAIL send: send_attempt_count missing")
    if not payload.get("sent_at"):
        raise SystemExit("FAIL send: sent_at missing")
    print(
        "PASS send: "
        f"mailbox={payload.get('mailbox')} "
        f"attempts={payload['send_attempt_count']}"
    )
else:
    raise SystemExit(f"FAIL unknown label: {label}")
PY
}

request_json "POST" "scan" "/v1/at0-mail/scan?max_results=${MAX_RESULTS}"
request_json "GET" "health" "/v1/at0-mail/health"
request_json "GET" "mailboxes" "/v1/at0-mail/mailboxes"
request_json "GET" "spark" "/v1/at0-mail/spark-profile"
request_json "GET" "dashboard" "/v1/at0-mail/dashboard"
request_json "GET" "messages" "/v1/at0-mail/messages?limit=1"
request_json "GET" "drafts" "/v1/at0-mail/drafts?limit=1"

if [ -n "${SEND_DRAFT_ID}" ]; then
  request_json "POST" "send" "/v1/at0-mail/drafts/${SEND_DRAFT_ID}/send"
  echo "PASS at0-herald-mail smoke: scan, health, mailboxes, spark, dashboard, messages, drafts, send reachable"
else
  echo "PASS at0-herald-mail smoke: scan, health, mailboxes, spark, dashboard, messages, drafts reachable"
fi
