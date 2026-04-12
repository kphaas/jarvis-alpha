#!/opt/homebrew/bin/bash
# smoke_lib.sh — TD-57 v1. See docs/SMOKE_LIB_DESIGN.md. DO NOT EXPAND SCOPE — use TD-58.

if [[ "${BASH_VERSINFO[0]}" -lt 5 ]]; then
    echo "smoke_lib.sh requires bash 5+ (got ${BASH_VERSION}). Install: brew install bash" >&2
    # shellcheck disable=SC2317
    return 1 2>/dev/null || exit 1
fi

set -euo pipefail

: "${PSQL:=/opt/homebrew/Cellar/postgresql@16/16.13/bin/psql}"

psql_capture_uuid() {
  local -n _psql_capture_uuid_conn="$1"
  local sql="$2"
  local out
  out=$( "${_psql_capture_uuid_conn[@]}" -tAc "$sql" \
    | grep -E '^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$' \
    | head -1 )
  printf '%s' "$out"
}

psql_admin() {
  local sql="$1"
  shift
  "$PSQL" -X -v ON_ERROR_STOP=1 -tA -U jarvisbrain -d jarvis_alpha "$@" -c "$sql"
}

assert_row_count() {
  local -n _assert_row_count_conn="$1"
  local sql="$2"
  local expected="$3"
  local test_name="$4"
  local got
  got=$( "${_assert_row_count_conn[@]}" -tAc "$sql" | tr -d '[:space:]' )
  if [[ "$got" == "$expected" ]]; then
    return 0
  fi
  if [[ "$test_name" == "DELETE_rowcount" ]]; then
    echo "❌ DELETE affected ${got} rows (expected ${expected})" >&2
  else
    echo "❌ ${test_name}, got ${got}" >&2
  fi
  exit 1
}
