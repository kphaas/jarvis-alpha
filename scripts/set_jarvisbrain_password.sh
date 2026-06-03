#!/usr/bin/env bash
# set_jarvisbrain_password.sh — set jarvisbrain password from ~/jarvis/.secrets.
# Runs on Brain only. Idempotent. Does not print password material.

set -euo pipefail

if [[ "$(hostname -s)" != "jarvis-brain" ]]; then
  echo "❌ Must run on Brain (current host: $(hostname -s))" >&2
  exit 1
fi

SECRETS_FILE="$HOME/jarvis/.secrets"
if [[ ! -f "$SECRETS_FILE" ]]; then
  echo "❌ Secrets file not found: $SECRETS_FILE" >&2
  exit 1
fi

set -a
# shellcheck source=/dev/null
source "$SECRETS_FILE"
set +a

if [[ -z "${POSTGRES_PASSWORD:-}" ]]; then
  echo "❌ POSTGRES_PASSWORD not set in $SECRETS_FILE" >&2
  exit 1
fi

PSQL="${PSQL:-/opt/homebrew/Cellar/postgresql@16/16.13/bin/psql}"
export PGPASSWORD="$POSTGRES_PASSWORD"

echo "🔐 Setting jarvisbrain Postgres password..."
"$PSQL" -h localhost -U jarvisbrain -d jarvis_alpha -v postgres_pw="$POSTGRES_PASSWORD" <<'SQL'
\set QUIET on
ALTER ROLE jarvisbrain WITH PASSWORD :'postgres_pw';
SQL

PASSWORD_TYPE=$(
  "$PSQL" -h localhost -U jarvisbrain -d jarvis_alpha -tA <<'SQL'
SELECT CASE
  WHEN rolpassword IS NULL THEN 'none'
  WHEN rolpassword LIKE 'SCRAM-SHA-256$%' THEN 'scram'
  ELSE 'other'
END
FROM pg_authid
WHERE rolname = 'jarvisbrain';
SQL
)

if [[ "$PASSWORD_TYPE" != "scram" ]]; then
  echo "❌ jarvisbrain password verification failed: $PASSWORD_TYPE" >&2
  exit 1
fi

echo "✅ jarvisbrain password is set with SCRAM storage."
