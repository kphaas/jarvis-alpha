#!/usr/bin/env bash
# smoke_memory_secdef.sh — verify Stage 5a MemoryService SECURITY DEFINER functions
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
echo "=== Stage 5a Smoke Test — Memory SECURITY DEFINER Functions ==="
echo ""

: <<'TEST_LABELS'
TEST 1
TEST 2
TEST 3
TEST 4
TEST 5
TEST 6
TEST 7
TEST 8
TEST 9
TEST 10
TEST_LABELS

echo "TEST 1: All 5 functions exist, owner=jarvisbrain, is_secdef=t"
"$PSQL" -U jarvisbrain -d jarvis_alpha -tAc "
  SELECT p.proname, r.rolname AS owner, p.prosecdef AS is_secdef
  FROM pg_proc p
  JOIN pg_roles r ON p.proowner = r.oid
  WHERE p.proname IN (
    'store_conversation_memory',
    'save_semantic_memory',
    'bump_memory_access',
    'forget_memory_by_topic',
    'forget_working_memory'
  )
  ORDER BY p.proname;
"
echo "Expected: 5 rows, all owner=jarvisbrain, is_secdef=t"
echo ""

echo "TEST 2: search_path = pg_catalog, public (no pg_temp)"
"$PSQL" -U jarvisbrain -d jarvis_alpha -tAc "
  SELECT proname, proconfig
  FROM pg_proc
  WHERE proname = 'store_conversation_memory';
"
echo "Expected: proconfig contains search_path=pg_catalog, public"
echo ""

echo "TEST 3: Execute grants for writer + jarvisbrain, no PUBLIC"
"$PSQL" -U jarvisbrain -d jarvis_alpha -tAc "
  SELECT p.proname, p.proacl::text
  FROM pg_proc p
  WHERE p.proname IN (
    'store_conversation_memory',
    'save_semantic_memory',
    'bump_memory_access',
    'forget_memory_by_topic',
    'forget_working_memory'
  )
  ORDER BY p.proname;
"
echo "Expected: ACL includes jarvis_alpha_writer=X and jarvisbrain=X, excludes PUBLIC execute"
echo ""

echo "TEST 4: store_conversation_memory end-to-end as jarvisbrain"
STORE_ID=$("$PSQL" -U jarvisbrain -d jarvis_alpha -tAc "
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
")
echo "Returned id: $STORE_ID"
echo "Expected: a UUID string"
echo ""

echo "TEST 5: save_semantic_memory cap check path (normal insert)"
"$PSQL" -U jarvisbrain -d jarvis_alpha -tAc "
  SELECT public.save_semantic_memory(
    gen_random_uuid(),
    'smoke_test_semantic_fact',
    'preference'
  );
"
echo "Expected: JSON with saved=true"
echo ""

echo "TEST 6: bump_memory_access callable"
"$PSQL" -U jarvisbrain -d jarvis_alpha -tAc "
  SELECT public.bump_memory_access(ARRAY['$STORE_ID'::uuid]);
"
echo "Expected: 1"
echo ""

echo "TEST 7: forget_working_memory removes test row"
"$PSQL" -U jarvisbrain -d jarvis_alpha -tAc "
  SELECT public.forget_working_memory('smoke_test_stage5a');
"
echo "Expected: 1"
echo ""

echo "TEST 8: forget_memory_by_topic removes topic row"
"$PSQL" -U jarvisbrain -d jarvis_alpha -tAc "
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
"
"$PSQL" -U jarvisbrain -d jarvis_alpha -tAc "
  SELECT public.forget_memory_by_topic('smoke_test_stage5a', 'smoke_topic_xyz');
"
echo "Expected: 1"
echo ""

echo "TEST 9: jarvis_alpha_writer can execute all 5 (smoke via store)"
export PGPASSWORD="$PASSWORD"
WRITER_ID=$("$PSQL" -h localhost -U jarvis_alpha_writer -d jarvis_alpha -tAc "
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
")
unset PGPASSWORD
echo "Returned id as writer: $WRITER_ID"
echo "Expected: a UUID string"
echo ""

echo "TEST 10: Cleanup"
"$PSQL" -U jarvisbrain -d jarvis_alpha -tAc "
  DELETE FROM alpha_semantic_memory WHERE fact LIKE 'smoke_test%';
"
"$PSQL" -U jarvisbrain -d jarvis_alpha -tAc "
  DELETE FROM alpha_conversation_memory WHERE user_id LIKE 'smoke_test%';
"
echo "Expected: smoke_test rows removed from semantic + conversation tables"
echo ""

echo "=== Smoke Test Script Ready ==="
echo "Do not run on Air. Run on Brain only."
