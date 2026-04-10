#!/usr/bin/env bash
# smoke_5d1_watchdog_agent.sh — verify watchdog_agent writer cutover (Stage 5d.1)
# Runs on Brain only.

set -euo pipefail

if [[ "$(hostname -s)" != "jarvis-brain" ]]; then
  echo "❌ Must run on Brain (current host: $(hostname -s))" >&2
  exit 1
fi

PSQL="/opt/homebrew/Cellar/postgresql@16/16.13/bin/psql"

# Source the secrets file to get the DSN
set -a
source ~/jarvis/.secrets
set +a

if [[ -z "${ALPHA_DB_DSN_WATCHDOG_AGENT:-}" ]]; then
  echo "❌ ALPHA_DB_DSN_WATCHDOG_AGENT not set in ~/jarvis/.secrets" >&2
  exit 1
fi

echo ""
echo "=== Smoke Test — Stage 5d.1 watchdog_agent cutover ==="
echo ""

# Test 1: Connection as writer
echo "Test 1: Connect as jarvis_alpha_writer"
ROLE=$("$PSQL" -X "$ALPHA_DB_DSN_WATCHDOG_AGENT" -tAc "SELECT current_user;")
if [[ "$ROLE" != "jarvis_alpha_writer" ]]; then
  echo "❌ Expected current_user=jarvis_alpha_writer, got: $ROLE" >&2
  exit 1
fi
echo "OK: connected as $ROLE"
echo ""

# Test 2: SELECT alpha_node_registry (no RLS, must work)
echo "Test 2: SELECT alpha_node_registry"
COUNT=$("$PSQL" -X "$ALPHA_DB_DSN_WATCHDOG_AGENT" -tAc "SELECT count(*)::text FROM alpha_node_registry;")
if [[ "$COUNT" -lt 1 ]]; then
  echo "❌ alpha_node_registry returned 0 rows (expected >=1)" >&2
  exit 1
fi
echo "OK: alpha_node_registry has $COUNT rows"
echo ""

# Test 3: INSERT alpha_watchdog_events with rls.user_id='system' set
echo "Test 3: INSERT alpha_watchdog_events with rls.user_id='system'"
TEST_ID=$("$PSQL" -X "$ALPHA_DB_DSN_WATCHDOG_AGENT" -tAc "
  BEGIN;
  SELECT set_config('rls.user_id', 'system', true);
  WITH ins AS (
    INSERT INTO alpha_watchdog_events (service_name, node, event_type, error_message, action_taken)
    VALUES ('smoke_5d1_test', 'brain', 'check_error', 'smoke_5d1_watchdog_agent test row', 'none')
    RETURNING id
  )
  SELECT id::text FROM ins;
  COMMIT;
" | grep -E '^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$' | head -1)
if [[ -z "$TEST_ID" ]]; then
  echo "❌ INSERT failed" >&2
  exit 1
fi
echo "OK: inserted id=$TEST_ID"
echo ""

# Test 4: DELETE the test row (with rls.user_id='system')
echo "Test 4: DELETE test row"
"$PSQL" -X "$ALPHA_DB_DSN_WATCHDOG_AGENT" -c "
  BEGIN;
  SELECT set_config('rls.user_id', 'system', true);
  DELETE FROM alpha_watchdog_events WHERE id = '$TEST_ID'::uuid;
  COMMIT;
" > /dev/null
echo "OK: deleted $TEST_ID"
echo ""

# Test 5: Negative — INSERT WITHOUT setting rls.user_id must FAIL
echo "Test 5 (NEGATIVE): INSERT without rls.user_id must be REJECTED by RLS"
set +e
OUT=$("$PSQL" -X "$ALPHA_DB_DSN_WATCHDOG_AGENT" -tAc "
  INSERT INTO alpha_watchdog_events (service_name, node, event_type, error_message, action_taken)
  VALUES ('smoke_5d1_test', 'brain', 'check_error', 'smoke_5d1 negative test', 'none')
  RETURNING id;
" 2>&1)
RC=$?
set -e

if [[ "$RC" -eq 0 ]]; then
  echo "❌ FATAL: INSERT without rls.user_id succeeded — RLS NOT enforced!" >&2
  echo "Output: $OUT" >&2
  # Try to clean up the leaked row
  "$PSQL" -X -U jarvisbrain -d jarvis_alpha -c "
    DELETE FROM alpha_watchdog_events WHERE error_message = 'smoke_5d1 negative test';
  " > /dev/null 2>&1 || true
  exit 1
fi
echo "OK: RLS rejected the insert (psql exit $RC)"
echo ""

echo "=== ALL TESTS PASSED — Stage 5d.1 ready to ship ==="
exit 0
