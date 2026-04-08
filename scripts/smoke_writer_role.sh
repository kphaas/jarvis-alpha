#!/usr/bin/env bash
# smoke_writer_role.sh — verify jarvis_alpha_writer role is correctly configured
# Runs on Brain only.

set -euo pipefail

if [[ "$(hostname -s)" != "jarvis-brain" ]]; then
  echo "❌ Must run on Brain (current host: $(hostname -s))" >&2
  exit 1
fi

PSQL="/opt/homebrew/Cellar/postgresql@16/16.13/bin/psql"
SECRETS_FILE="$HOME/jarvis/.secrets"
PASSWORD=$(grep '^ALPHA_WRITER_DB_PASSWORD=' "$SECRETS_FILE" | cut -d= -f2- | tr -d '"')

if [[ -z "$PASSWORD" ]]; then
  echo "❌ ALPHA_WRITER_DB_PASSWORD not set in $SECRETS_FILE" >&2
  exit 1
fi

echo ""
echo "=== Stage 2 Smoke Test — jarvis_alpha_writer ==="
echo ""

# Test 1: Role exists with correct attributes
echo "TEST 1: Role exists, LOGIN, NOBYPASSRLS"
"$PSQL" -U jarvisbrain -d jarvis_alpha -tAc \
  "SELECT rolname, rolcanlogin, rolbypassrls FROM pg_roles WHERE rolname = 'jarvis_alpha_writer';"
echo "Expected: jarvis_alpha_writer|t|f"
echo ""

# Test 2: Grants present on key tables
echo "TEST 2: DML grants on alpha_conversation_memory"
"$PSQL" -U jarvisbrain -d jarvis_alpha -tAc \
  "SELECT privilege_type FROM information_schema.table_privileges WHERE grantee = 'jarvis_alpha_writer' AND table_name = 'alpha_conversation_memory' ORDER BY privilege_type;"
echo "Expected: DELETE INSERT SELECT UPDATE (one per line)"
echo ""

# Test 3: Password auth works
echo "TEST 3: Password authentication via localhost"
export PGPASSWORD="$PASSWORD"
"$PSQL" -h localhost -U jarvis_alpha_writer -d jarvis_alpha -tAc "SELECT current_user;"
unset PGPASSWORD
echo "Expected: jarvis_alpha_writer"
echo ""

# Test 4: Can SELECT but RLS blocks unscoped reads on conversation_memory
# Note: alpha_conversation_memory currently has RLS enabled (relrowsecurity=t) but
# jarvisbrain bypasses as superuser. jarvis_alpha_writer should see 0 rows without GUCs set.
echo "TEST 4: RLS enforcement — writer sees 0 rows without GUCs"
export PGPASSWORD="$PASSWORD"
ROWS=$("$PSQL" -h localhost -U jarvis_alpha_writer -d jarvis_alpha -tAc \
  "SELECT count(*) FROM alpha_conversation_memory;")
unset PGPASSWORD
echo "Row count: $ROWS"
echo "Expected: 0 (RLS blocks reads — superuser bypass disabled on this role)"
echo ""

# Test 5: Default privileges set
echo "TEST 5: ALTER DEFAULT PRIVILEGES registered"
"$PSQL" -U jarvisbrain -d jarvis_alpha -tAc \
  "SELECT count(*) FROM pg_default_acl d JOIN pg_roles r ON d.defaclrole = r.oid WHERE r.rolname = 'jarvisbrain' AND d.defaclnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'public');"
echo "Expected: 2 (one for TABLES, one for SEQUENCES)"
echo ""

# Test 6: Legacy role preservation
echo "TEST 6: Legacy role preservation (TD-38)"
"$PSQL" -U jarvisbrain -d jarvis_alpha -tAc \
  "SELECT has_schema_privilege('jarvis', 'public', 'USAGE'), has_schema_privilege('jarvis_app', 'public', 'USAGE');"
echo "Expected: t|t (both legacy roles still have schema USAGE after REVOKE)"
echo ""

# Test 7: Legacy jarvis BYPASSRLS defanged
echo "TEST 7: Legacy jarvis BYPASSRLS defanged (TD-38)"
"$PSQL" -U jarvisbrain -d jarvis_alpha -tAc \
  "SELECT rolbypassrls FROM pg_roles WHERE rolname = 'jarvis';"
echo "Expected: f (BYPASSRLS removed — no longer a RLS escape hatch)"
echo ""

echo "=== Smoke Test Complete ==="
echo "If any test output does not match expected, STOP and investigate before Stage 3."
