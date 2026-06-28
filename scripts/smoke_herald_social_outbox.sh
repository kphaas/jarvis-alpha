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
elif label == "cadence":
    for key in ("today", "next_due_date", "approved_ready_count"):
        if key not in payload:
            raise SystemExit(f"FAIL cadence: missing {key}")
    print(
        "PASS cadence: "
        f"next_due={payload.get('next_due_date')} "
        f"ready={payload.get('approved_ready_count')}"
    )
elif label in {"create", "weekly"}:
    drafts = payload.get("drafts")
    if not isinstance(drafts, list) or not drafts:
        raise SystemExit(f"FAIL {label}: no drafts returned")
    for draft in drafts:
        if draft.get("status") != "needs_review":
            raise SystemExit(f"FAIL {label}: status={draft.get('status')}")
        if "draft_only_no_publish" not in draft.get("safety_flags", []):
            raise SystemExit(f"FAIL {label}: draft-only flag missing")
        if label == "weekly" and draft.get("platform") != "linkedin":
            raise SystemExit(f"FAIL weekly: platform={draft.get('platform')}")
    Path(sys.argv[2]).with_suffix(".id").write_text(drafts[0]["id"], encoding="utf-8")
    print(f"PASS {label}: drafts={len(drafts)}")
elif label == "engagement":
    if payload.get("status") != "needs_reply":
        raise SystemExit(f"FAIL engagement: status={payload.get('status')}")
    if payload.get("platform") != "linkedin":
        raise SystemExit(f"FAIL engagement: platform={payload.get('platform')}")
    Path(sys.argv[2]).with_suffix(".id").write_text(payload["id"], encoding="utf-8")
    print("PASS engagement: needs_reply item created")
elif label == "engagements":
    items = payload.get("items")
    if not isinstance(items, list):
        raise SystemExit("FAIL engagements: items missing")
    print(f"PASS engagements: count={len(items)}")
elif label == "reply":
    drafts = payload.get("drafts")
    if not isinstance(drafts, list) or len(drafts) < 3:
        raise SystemExit("FAIL reply: expected three reply options")
    styles = set()
    ids = []
    for draft in drafts:
        if draft.get("draft_kind") != "reply":
            raise SystemExit(f"FAIL reply: kind={draft.get('draft_kind')}")
        if draft.get("platform") != "linkedin":
            raise SystemExit(f"FAIL reply: platform={draft.get('platform')}")
        if draft.get("status") != "needs_review":
            raise SystemExit(f"FAIL reply: status={draft.get('status')}")
        flags = set(draft.get("safety_flags", []))
        styles.update(flag for flag in flags if flag.startswith("reply_style_"))
        ids.append(draft["id"])
    expected_styles = {
        "reply_style_strong_short",
        "reply_style_practical",
        "reply_style_warm",
    }
    if not expected_styles.issubset(styles):
        raise SystemExit(f"FAIL reply: missing styles {expected_styles - styles}")
    Path(sys.argv[2]).with_suffix(".id").write_text(ids[0], encoding="utf-8")
    Path(sys.argv[2]).with_suffix(".ids").write_text("\n".join(ids), encoding="utf-8")
    print(f"PASS reply: LinkedIn reply options created={len(drafts)}")
elif label == "engagement_status":
    if payload.get("status") != "archived":
        raise SystemExit(f"FAIL engagement_status: status={payload.get('status')}")
    print("PASS engagement_status: archived")
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
request_json "GET" "cadence" "/v1/herald/social/linkedin/cadence"
request_json "POST" "weekly" "/v1/herald/social/linkedin/weekly"

WEEKLY_DRAFT_ID="$(cat "${TMP_DIR}/weekly.id")"
ARCHIVE_BODY="${TMP_DIR}/archive.json"
printf '{"status":"archived","reviewer_notes":"smoke cleanup"}\n' >"${ARCHIVE_BODY}"
request_json "POST" "archive" "/v1/herald/social/drafts/${WEEKLY_DRAFT_ID}/status" "${ARCHIVE_BODY}"

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

printf '{"status":"archived","reviewer_notes":"smoke cleanup"}\n' >"${ARCHIVE_BODY}"
request_json "POST" "archive" "/v1/herald/social/drafts/${SMOKE_DRAFT_ID}/status" "${ARCHIVE_BODY}"

ENGAGEMENT_BODY="${TMP_DIR}/engagement.json"
"${PYTHON_BIN}" >"${ENGAGEMENT_BODY}" <<'PY'
import json

print(json.dumps({
    "author_name": "Smoke Reviewer",
    "item_text": "Can AT0 draft LinkedIn replies without posting automatically?",
    "item_url": "https://www.linkedin.com/feed/update/urn:li:share:smoke",
    "account_label": "AT0",
}))
PY

request_json "POST" "engagement" "/v1/herald/social/linkedin/engagements" "${ENGAGEMENT_BODY}"
ENGAGEMENT_ID="$(cat "${TMP_DIR}/engagement.id")"
request_json "GET" "engagements" "/v1/herald/social/linkedin/engagements?status=needs_reply&limit=5"
request_json "POST" "reply" "/v1/herald/social/linkedin/engagements/${ENGAGEMENT_ID}/draft-reply"
printf '{"status":"archived","reviewer_notes":"smoke cleanup"}\n' >"${ARCHIVE_BODY}"
while IFS= read -r REPLY_DRAFT_ID; do
  [ -n "${REPLY_DRAFT_ID}" ] || continue
  request_json "POST" "archive" "/v1/herald/social/drafts/${REPLY_DRAFT_ID}/status" "${ARCHIVE_BODY}"
done <"${TMP_DIR}/reply.ids"
ENGAGEMENT_STATUS_BODY="${TMP_DIR}/engagement_status.json"
printf '{"status":"archived"}\n' >"${ENGAGEMENT_STATUS_BODY}"
request_json "POST" "engagement_status" "/v1/herald/social/linkedin/engagements/${ENGAGEMENT_ID}/status" "${ENGAGEMENT_STATUS_BODY}"
request_json "GET" "drafts" "/v1/herald/social/drafts?status=all&limit=1"

echo "PASS herald-social-outbox smoke: platforms, cadence, weekly, create, engagement, reply draft, archive, drafts reachable"
