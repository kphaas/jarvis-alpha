#!/usr/bin/env bash
# smoke_memory_secdef.sh — verify MemoryService SECURITY DEFINER functions.
# Runs on Brain only. Fails loudly on auth, owner, search_path, ACL, or call regressions.

set -euo pipefail

if [[ "$(hostname -s)" != "jarvis-brain" ]]; then
  echo "❌ Must run on Brain (current host: $(hostname -s))" >&2
  exit 1
fi

PSQL="${PSQL:-/opt/homebrew/Cellar/postgresql@16/16.13/bin/psql}"
DB="${DB:-jarvis_alpha}"
OWNER_ROLE="${OWNER_ROLE:-jarvisbrain}"
WRITER_ROLE="${WRITER_ROLE:-jarvis_alpha_writer}"
APP_ROLE="${APP_ROLE:-jarvis_alpha_app}"

if [[ -f "${HOME}/jarvis/.secrets" ]]; then
  SECRETS_FILE="${HOME}/jarvis/.secrets"
elif [[ -f "${HOME}/.secrets" ]]; then
  SECRETS_FILE="${HOME}/.secrets"
else
  echo "❌ secrets file not found" >&2
  exit 1
fi

set -a
# shellcheck source=/dev/null
source "$SECRETS_FILE"
set +a

if [[ -z "${POSTGRES_PASSWORD:-}" ]]; then
  echo "❌ POSTGRES_PASSWORD missing from $SECRETS_FILE" >&2
  exit 1
fi
if [[ -z "${ALPHA_WRITER_DB_PASSWORD:-}" ]]; then
  echo "❌ ALPHA_WRITER_DB_PASSWORD missing from $SECRETS_FILE" >&2
  exit 1
fi

OWNER_CONN=(-h localhost -U "$OWNER_ROLE" -d "$DB")
WRITER_CONN=(-h localhost -U "$WRITER_ROLE" -d "$DB")

MEMORY_FUNCTIONS=(
  bump_memory_access
  forget_memory_by_topic
  forget_working_memory
  review_semantic_memory
  save_semantic_memory
  save_semantic_memory_with_provenance
  store_conversation_memory
)

failures=0
pass() { printf '  PASS  %s\n' "$1"; }
fail() {
  printf '  FAIL  %s\n' "$1" >&2
  failures=1
}

owner_psql() {
  PGPASSWORD="$POSTGRES_PASSWORD" "$PSQL" "${OWNER_CONN[@]}" "$@"
}

writer_psql() {
  PGPASSWORD="$ALPHA_WRITER_DB_PASSWORD" "$PSQL" "${WRITER_CONN[@]}" "$@"
}

cleanup_smoke_rows() {
  owner_psql -tAc "
    DELETE FROM alpha_buddy_events
    WHERE source = 'memory_secdef_smoke'
       OR (
         source = 'semantic_memory_review'
         AND payload->>'source_surface' = 'memory_secdef_smoke'
       );
    DELETE FROM alpha_semantic_memory WHERE fact LIKE 'smoke_test%';
    DELETE FROM alpha_conversation_memory WHERE user_id LIKE 'smoke_test%';
  " >/dev/null
}

sql_function_names() {
  local joined=""
  local fn
  for fn in "${MEMORY_FUNCTIONS[@]}"; do
    if [[ -n "$joined" ]]; then
      joined+=", "
    fi
    joined+="'$fn'"
  done
  printf '%s' "$joined"
}

assert_eq() {
  local got="$1"
  local expected="$2"
  local label="$3"
  if [[ "$got" == "$expected" ]]; then
    pass "$label"
  else
    fail "$label expected=$expected got=$got"
  fi
}

echo ""
echo "=== Memory Smoke — SECURITY DEFINER Functions ==="
echo ""

FUNCTION_NAMES="$(sql_function_names)"
EXPECTED_COUNT="${#MEMORY_FUNCTIONS[@]}"

trap 'cleanup_smoke_rows >/dev/null 2>&1 || true' EXIT
cleanup_smoke_rows

echo "TEST 1: memory functions exist, are SECDEF, and use contained owners"
owner_psql -tAc "
  SELECT p.proname, r.rolname AS owner, p.prosecdef AS is_secdef
  FROM pg_proc p
  JOIN pg_roles r ON p.proowner = r.oid
  WHERE p.proname IN ($FUNCTION_NAMES)
  ORDER BY p.proname;
"
contained_count="$(owner_psql -tAc "
  SELECT COUNT(*)
  FROM pg_proc p
  JOIN pg_roles r ON p.proowner = r.oid
  WHERE p.proname IN ($FUNCTION_NAMES)
    AND p.prosecdef
    AND r.rolname IN ('jarvis_alpha_owner', 'jarvisbrain');
")"
assert_eq "$contained_count" "$EXPECTED_COUNT" "all memory functions are SECDEF with contained owners"
echo ""

echo "TEST 2: search_path is locked to pg_catalog, public"
path_count="$(owner_psql -tAc "
  SELECT COUNT(*)
  FROM pg_proc
  WHERE proname IN ($FUNCTION_NAMES)
    AND proconfig @> ARRAY['search_path=pg_catalog, public'];
")"
assert_eq "$path_count" "$EXPECTED_COUNT" "all memory functions have safe search_path"
echo ""

echo "TEST 3: writer/app execute grants exist and PUBLIC execute is revoked"
grant_count="$(owner_psql -tAc "
  SELECT COUNT(*)
  FROM pg_proc
  WHERE proname IN ($FUNCTION_NAMES)
    AND has_function_privilege('$WRITER_ROLE', oid, 'EXECUTE')
    AND (
      NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_alpha_owner')
      OR has_function_privilege('jarvis_alpha_owner', oid, 'EXECUTE')
    )
    AND (
      NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$APP_ROLE')
      OR has_function_privilege('$APP_ROLE', oid, 'EXECUTE')
    )
    AND NOT EXISTS (
      SELECT 1
      FROM aclexplode(COALESCE(proacl, acldefault('f', proowner))) acl
      WHERE acl.grantee = 0
        AND acl.privilege_type = 'EXECUTE'
    );
")"
assert_eq "$grant_count" "$EXPECTED_COUNT" "memory function execute ACLs are restricted"
echo ""

echo "TEST 4: store_conversation_memory end-to-end as owner"
STORE_ID="$(owner_psql -tAc "
  SELECT public.store_conversation_memory(
    'smoke_test_stage5a',
    'smoke',
    'user',
    'smoke_test_stage5a content',
    array_fill(0.1, ARRAY[768])::vector,
    'working',
    false,
    0.5
  );
")"
if [[ "$STORE_ID" =~ ^[0-9a-fA-F-]{36}$ ]]; then
  pass "store_conversation_memory returned uuid"
else
  fail "store_conversation_memory returned unexpected value: $STORE_ID"
fi
echo ""

echo "TEST 5: save_semantic_memory_with_provenance routes health to review lane"
PROVENANCE_RESULT="$(writer_psql -tAc "
  SELECT public.save_semantic_memory_with_provenance(
    gen_random_uuid(),
    'smoke_test_health_review_lane',
    'health',
    '{\"source_surface\":\"memory_secdef_smoke\",\"source_action\":\"script\"}'::jsonb,
    NULL,
    NULL
  );
")"
echo "$PROVENANCE_RESULT"
if echo "$PROVENANCE_RESULT" | grep -q '"review_status": "pending_review"' \
  && echo "$PROVENANCE_RESULT" | grep -q '"review_required": true'; then
  pass "health semantic save enters pending_review"
else
  fail "health semantic save did not enter pending_review"
fi
echo ""

echo "TEST 6: save_semantic_memory legacy wrapper still works"
LEGACY_RESULT="$(owner_psql -tAc "
  SELECT public.save_semantic_memory(
    gen_random_uuid(),
    'smoke_test_semantic_fact',
    'preference'
  );
")"
echo "$LEGACY_RESULT"
if echo "$LEGACY_RESULT" | grep -q '"saved": true'; then
  pass "legacy save_semantic_memory returned saved=true"
else
  fail "legacy save_semantic_memory did not return saved=true"
fi
echo ""

echo "TEST 7: bump and forget functions are callable"
assert_eq "$(owner_psql -tAc "SELECT public.bump_memory_access(ARRAY['$STORE_ID'::uuid]);")" "1" "bump_memory_access returns 1"
assert_eq "$(owner_psql -tAc "SELECT public.forget_working_memory('smoke_test_stage5a');")" "1" "forget_working_memory removes owner row"
TOPIC_ID="$(owner_psql -tAc "
  SELECT public.store_conversation_memory(
    'smoke_test_stage5a',
    'smoke',
    'user',
    'smoke_topic_xyz',
    array_fill(0.1, ARRAY[768])::vector,
    'working',
    false,
    0.5
  );
")"
assert_eq "$(owner_psql -tAc "SELECT public.forget_memory_by_topic('smoke_test_stage5a', 'smoke_topic_xyz');")" "1" "forget_memory_by_topic removes topic row"
echo "  note  topic smoke id $TOPIC_ID"
echo ""

echo "TEST 8: writer role can execute store_conversation_memory"
WRITER_ID="$(writer_psql -tAc "
  SELECT public.store_conversation_memory(
    'smoke_test_writer',
    'smoke',
    'user',
    'smoke_test_writer content',
    array_fill(0.1, ARRAY[768])::vector,
    'working',
    false,
    0.5
  );
")"
if [[ "$WRITER_ID" =~ ^[0-9a-fA-F-]{36}$ ]]; then
  pass "writer role returned uuid"
else
  fail "writer role returned unexpected value: $WRITER_ID"
fi
echo ""

echo "TEST 9: cleanup"
cleanup_smoke_rows
pass "smoke rows removed"
echo ""

if [[ "$failures" == 0 ]]; then
  echo "=== Memory SECDEF smoke passed ==="
  exit 0
fi

echo "=== Memory SECDEF smoke failed ===" >&2
exit 1
