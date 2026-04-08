#!/usr/bin/env bash
# smoke_security_definer.sh — verify Stage 3 SECURITY DEFINER functions
# Runs on Brain only.

set -euo pipefail

if [[ "$(hostname -s)" != "jarvis-brain" ]]; then
  echo "❌ Must run on Brain (current host: $(hostname -s))" >&2
  exit 1
fi

PSQL="/opt/homebrew/Cellar/postgresql@16/16.13/bin/psql"
SECRETS_FILE="$HOME/jarvis/.secrets"
PASSWORD=$(grep '^ALPHA_WRITER_DB_PASSWORD=' "$SECRETS_FILE" | cut -d= -f2- | tr -d '"')

echo ""
echo "=== Stage 3 Smoke Test — SECURITY DEFINER Functions ==="
echo ""

# Test 1: All 6 functions exist with correct owner (promote removed — TD-40)
echo "TEST 1: Functions exist, owned by jarvisbrain"
"$PSQL" -U jarvisbrain -d jarvis_alpha -tAc "
  SELECT p.proname, r.rolname AS owner, p.prosecdef AS is_secdef
  FROM pg_proc p JOIN pg_roles r ON p.proowner = r.oid
  WHERE p.proname IN (
    'record_buddy_event',
    'evict_expired_working_memory',
    'evict_episodic_memory_older_than',
    'cap_episodic_memory',
    'cap_semantic_memory',
    'run_buddy_memory_maintenance'
  )
  ORDER BY p.proname;
"
echo "Expected: 6 rows, all owner=jarvisbrain, is_secdef=t"
echo ""

# Test 2: search_path is set correctly
echo "TEST 2: search_path = pg_catalog, public, pg_temp"
"$PSQL" -U jarvisbrain -d jarvis_alpha -tAc "
  SELECT p.proname, unnest(p.proconfig) AS config
  FROM pg_proc p
  WHERE p.proname = 'record_buddy_event';
"
echo "Expected: search_path=pg_catalog, public, pg_temp"
echo ""

# Test 3: REVOKE from PUBLIC, GRANT to jarvis_alpha_writer
echo "TEST 3: Execute grants"
"$PSQL" -U jarvisbrain -d jarvis_alpha -tAc "
  SELECT grantee, privilege_type
  FROM information_schema.routine_privileges
  WHERE routine_name = 'record_buddy_event'
  ORDER BY grantee;
"
echo "Expected: jarvis_alpha_writer|EXECUTE and jarvisbrain|EXECUTE (no PUBLIC)"
echo ""

# Test 4: record_buddy_event works as jarvisbrain (sentinel user)
echo "TEST 4: record_buddy_event via jarvisbrain (sentinel 'system')"
TEST_ID=$("$PSQL" -U jarvisbrain -d jarvis_alpha -tAc "
  SELECT public.record_buddy_event(
    'system',
    'system',
    'Stage 3 smoke test',
    'Testing SECURITY DEFINER function',
    1,
    'smoke_test',
    '{\"test\": true}'::jsonb
  );
")
echo "Inserted event id: $TEST_ID"
echo "Expected: a UUID string"
echo ""

# Test 5: invalid event_type rejected by CHECK constraint
echo "TEST 5: Invalid event_type rejected by CHECK constraint"
RESULT=$("$PSQL" -U jarvisbrain -d jarvis_alpha -tAc "
  SELECT public.record_buddy_event('system', 'bogus_type', 'x', 'x', 2, 'smoke_test', '{}'::jsonb);
" 2>&1 || true)
if echo "$RESULT" | grep -q "violates check constraint"; then
  echo "✅ Invalid event_type rejected"
else
  echo "❌ CHECK constraint bypass: $RESULT"
fi
echo ""

# Test 6: evict_expired_working_memory returns integer
echo "TEST 6: evict_expired_working_memory callable"
"$PSQL" -U jarvisbrain -d jarvis_alpha -tAc "SELECT public.evict_expired_working_memory();"
echo "Expected: a non-negative integer"
echo ""

# Test 7: run_buddy_memory_maintenance returns JSONB structure
echo "TEST 7: run_buddy_memory_maintenance returns JSONB"
"$PSQL" -U jarvisbrain -d jarvis_alpha -tAc "
  SELECT public.run_buddy_memory_maintenance('system');
"
echo "Expected: JSONB with evicted_working, evicted_episodic, capped_episodic, capped_semantic, errors fields"
echo ""

# Test 8: jarvis_alpha_writer can execute record_buddy_event
echo "TEST 8: jarvis_alpha_writer can execute SECURITY DEFINER"
export PGPASSWORD="$PASSWORD"
WRITER_ID=$("$PSQL" -h localhost -U jarvis_alpha_writer -d jarvis_alpha -tAc "
  SELECT public.record_buddy_event(
    'system',
    'system',
    'Stage 3 writer test',
    'Testing writer role execution',
    1,
    'smoke_test',
    '{\"writer\": true}'::jsonb
  );
")
unset PGPASSWORD
echo "Inserted event id as writer: $WRITER_ID"
echo "Expected: a UUID string (writer role can execute via GRANT)"
echo ""

# Test 9: Cleanup smoke test events
echo "TEST 9: Cleanup smoke test events"
"$PSQL" -U jarvisbrain -d jarvis_alpha -tAc "
  DELETE FROM alpha_buddy_events WHERE source LIKE 'smoke_test%' RETURNING id;
"
echo ""

# Test 10: dropped promote function (TD-40)
echo "TEST 10: promote function removed (TD-40)"
"$PSQL" -U jarvisbrain -d jarvis_alpha -tAc "
  SELECT count(*) FROM pg_proc WHERE proname = 'promote_episodic_to_semantic';
"
echo "Expected: 0 (function dropped — see TD-40)"
echo ""

echo "=== Smoke Test Complete ==="
echo "If any test output does not match expected, STOP and investigate before Stage 4."
