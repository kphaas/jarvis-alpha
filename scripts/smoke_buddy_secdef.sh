#!/usr/bin/env bash
# Stage 5c smoke test — verifies buddy_agent SECDEF wrappers and writer-role privileges.
#
# Usage:
#   ./smoke_buddy_secdef.sh <known_user_id>
#
# Connects as jarvis_alpha_writer for tests 1-3 and 6 (mirrors buddy runtime),
# and as jarvisbrain for the baseline-comparison parts of tests 4-5.
# Pass/fail is reported per-test; the script exits non-zero if any test fails.

set -uo pipefail

PSQL=/opt/homebrew/Cellar/postgresql@16/16.13/bin/psql
DB=jarvis_alpha
WRITER_ROLE=jarvis_alpha_writer
ADMIN_ROLE=jarvisbrain
USER_ID="${1:-}"

failures=0
pass() { printf '  PASS  %s\n' "$1"; }
fail() { printf '  FAIL  %s\n' "$1"; failures=1; }

run_writer() { "$PSQL" -U "$WRITER_ROLE" -d "$DB" -tAc "$1"; }
run_admin()  { "$PSQL" -U "$ADMIN_ROLE"  -d "$DB" -tAc "$1"; }

echo "Test 1 — list_active_memory_users exists, SECDEF, owned by $ADMIN_ROLE"
out=$(run_admin "SELECT prosecdef::text || '|' || proowner::regrole::text FROM pg_proc WHERE proname='list_active_memory_users';")
[[ "$out" == "true|$ADMIN_ROLE" ]] && pass "$out" || fail "got: $out"

echo "Test 2 — get_buddy_promotion_candidates exists, SECDEF, owned by $ADMIN_ROLE"
out=$(run_admin "SELECT prosecdef::text || '|' || proowner::regrole::text FROM pg_proc WHERE proname='get_buddy_promotion_candidates';")
[[ "$out" == "true|$ADMIN_ROLE" ]] && pass "$out" || fail "got: $out"

echo "Test 3 — $WRITER_ROLE has EXECUTE on both new functions"
out=$(run_admin "SELECT has_function_privilege('$WRITER_ROLE','public.list_active_memory_users()','EXECUTE')::text || '|' || has_function_privilege('$WRITER_ROLE','public.get_buddy_promotion_candidates(text)','EXECUTE')::text;")
[[ "$out" == "true|true" ]] && pass "$out" || fail "got: $out"

echo "Test 4 — list_active_memory_users() membership matches superuser SELECT DISTINCT"
wrapper_count=$(run_writer "SELECT cardinality(public.list_active_memory_users());")
baseline_count=$(run_admin "SELECT count(DISTINCT user_id) FROM alpha_conversation_memory WHERE user_id IS NOT NULL;")
[[ "$wrapper_count" == "$baseline_count" && "$wrapper_count" -ge 1 ]] && pass "wrapper=$wrapper_count baseline=$baseline_count" || fail "wrapper=$wrapper_count baseline=$baseline_count"

if [[ -n "$USER_ID" ]]; then
  echo "Test 5 — get_buddy_promotion_candidates('$USER_ID') subset of baseline, ≤5 rows"
  wrapper_ids=$(run_writer "SELECT id FROM public.get_buddy_promotion_candidates('$USER_ID') ORDER BY id;")
  baseline_ids=$(run_admin "SELECT id FROM alpha_conversation_memory WHERE user_id='$USER_ID' AND tier='working' AND created_at < now() - interval '20 hours' ORDER BY id;")
  wrapper_n=$(printf '%s\n' "$wrapper_ids" | grep -c .)
  if [[ "$wrapper_n" -le 5 ]]; then
    subset_ok=1
    while IFS= read -r line; do
      [[ -z "$line" ]] && continue
      printf '%s\n' "$baseline_ids" | grep -qx "$line" || subset_ok=0
    done <<< "$wrapper_ids"
    [[ "$subset_ok" == 1 ]] && pass "rows=$wrapper_n, all in baseline" || fail "wrapper rows not a subset of baseline"
  else
    fail "wrapper returned $wrapper_n rows (>5)"
  fi
else
  echo "Test 5 — SKIPPED (pass <known_user_id> as arg 1 to enable)"
fi

echo "Test 6 — naked SELECT from alpha_conversation_memory as $WRITER_ROLE blocked by FORCE RLS"
out=$(run_writer "SELECT count(*) FROM alpha_conversation_memory;")
[[ "$out" == "0" ]] && pass "writer sees 0 rows (RLS enforced)" || fail "writer sees $out rows — FORCE RLS regressed"

echo
if [[ "$failures" == 0 ]]; then
  echo "ALL TESTS PASSED"
  exit 0
else
  echo "ONE OR MORE TESTS FAILED"
  exit 1
fi
