#!/usr/bin/env bash
# Smoke Herald social draft-only outbox without publishing to any social platform.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

BASE_URL="${ALPHA_BASE_URL:-https://jarvis-brain.tail40ed36.ts.net:8186}"
TIMEOUT_SEC="${HERALD_SOCIAL_SMOKE_TIMEOUT_SEC:-30}"
TOKEN="${HERALD_SOCIAL_SMOKE_TOKEN:-${ALPHA_SERVICE_TOKEN:-}}"
TOPIC="${HERALD_SOCIAL_SMOKE_TOPIC:-Smoke proof for Herald social approval outbox. Do not publish.}"
if [ -x "${REPO_ROOT}/.venv/bin/python" ]; then
  DEFAULT_PYTHON="${REPO_ROOT}/.venv/bin/python"
else
  DEFAULT_PYTHON="python3"
fi
PYTHON_BIN="${HERALD_SOCIAL_SMOKE_PYTHON:-${DEFAULT_PYTHON}}"

if [ -z "${TOKEN}" ] && [ -f "${HOME}/jarvis/.secrets" ]; then
  set +u
  # shellcheck disable=SC1090
  source "${HOME}/jarvis/.secrets"
  set -u
  TOKEN="${HERALD_SOCIAL_SMOKE_TOKEN:-${ALPHA_SERVICE_TOKEN:-}}"
fi

if [ -z "${TOKEN}" ]; then
  SMOKE_ISS="${HERALD_SOCIAL_SMOKE_ISS:-brain}"
  TOKEN="$(
    "${PYTHON_BIN}" "${REPO_ROOT}/scripts/gen_service_token.py" \
      --iss "${SMOKE_ISS}" \
      --actor-type service \
      --scopes "herald.read,herald.write" \
      --days 1 2>/dev/null || true
  )"
fi

if [ -z "${TOKEN}" ]; then
  echo "SKIP: set HERALD_SOCIAL_SMOKE_TOKEN or run on a node with a service private key." >&2
  exit 2
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

request_json() {
  local method="$1"
  local label="$2"
  local path="$3"
  local body_path="${4:-}"
  local output_path="${TMP_DIR}/${label}.json"
  local http_code
  local curl_args=(
    -skS
    --max-time "${TIMEOUT_SEC}"
    -o "${output_path}"
    -w "%{http_code}"
    -X "${method}"
    -H "Authorization: Bearer ${TOKEN}"
    -H "Accept: application/json"
  )
  if [ -n "${body_path}" ]; then
    curl_args+=(-H "Content-Type: application/json" --data-binary "@${body_path}")
  fi

  if ! http_code="$(curl "${curl_args[@]}" "${BASE_URL}${path}")"; then
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
forbidden_keys = {"access_token", "private_key", "password", "client_secret"}


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

if label == "platforms":
    platforms = payload.get("platforms")
    if not isinstance(platforms, list) or not platforms:
        raise SystemExit("FAIL platforms: no active profiles")
    names = {row.get("platform") for row in platforms}
    if not {"x", "linkedin"}.issubset(names):
        raise SystemExit(f"FAIL platforms: missing expected profiles {names}")
    print(f"PASS platforms: count={len(platforms)}")
elif label == "create":
    drafts = payload.get("drafts")
    if not isinstance(drafts, list) or not drafts:
        raise SystemExit("FAIL create: no drafts returned")
    for draft in drafts:
        if draft.get("status") != "needs_review":
            raise SystemExit(f"FAIL create: status={draft.get('status')}")
        if "draft_only_no_publish" not in draft.get("safety_flags", []):
            raise SystemExit("FAIL create: draft-only flag missing")
    Path(sys.argv[2]).with_suffix(".id").write_text(drafts[0]["id"], encoding="utf-8")
    print(f"PASS create: drafts={len(drafts)}")
elif label == "archive":
    if payload.get("status") != "archived":
        raise SystemExit(f"FAIL archive: status={payload.get('status')}")
    print("PASS archive: archived one smoke draft")
elif label == "drafts":
    if not isinstance(payload.get("drafts"), list):
        raise SystemExit("FAIL drafts: drafts missing")
    print(f"PASS drafts: count={len(payload['drafts'])}")
else:
    raise SystemExit(f"FAIL unknown label: {label}")
PY
}

request_json "GET" "platforms" "/v1/herald/social/platforms"

CREATE_BODY="${TMP_DIR}/create.json"
"${PYTHON_BIN}" - "${TOPIC}" >"${CREATE_BODY}" <<'PY'
import json
import sys

print(json.dumps({
    "topic": sys.argv[1],
    "platforms": ["x", "linkedin"],
    "account_label": "AT0",
}))
PY

request_json "POST" "create" "/v1/herald/social/drafts" "${CREATE_BODY}"
SMOKE_DRAFT_ID="$(cat "${TMP_DIR}/create.id")"

ARCHIVE_BODY="${TMP_DIR}/archive.json"
printf '{"status":"archived","reviewer_notes":"smoke cleanup"}\n' >"${ARCHIVE_BODY}"
request_json "POST" "archive" "/v1/herald/social/drafts/${SMOKE_DRAFT_ID}/status" "${ARCHIVE_BODY}"
request_json "GET" "drafts" "/v1/herald/social/drafts?status=all&limit=1"

echo "PASS herald-social-outbox smoke: platforms, create, archive, drafts reachable"
