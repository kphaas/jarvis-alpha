#!/usr/bin/env bash
# set_writer_password.sh — set jarvis_alpha_writer password from ~/jarvis/.secrets
# Runs on Brain only. Idempotent. Reads ALPHA_WRITER_DB_PASSWORD, runs ALTER ROLE.

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

PASSWORD=$(grep '^ALPHA_WRITER_DB_PASSWORD=' "$SECRETS_FILE" | cut -d= -f2- | tr -d '"')
if [[ -z "$PASSWORD" ]]; then
  echo "❌ ALPHA_WRITER_DB_PASSWORD not set in $SECRETS_FILE" >&2
  exit 1
fi

PSQL="/opt/homebrew/Cellar/postgresql@16/16.13/bin/psql"

# Use psql -v to avoid password in shell history or process list
echo "🔐 Setting jarvis_alpha_writer password..."
"$PSQL" -U jarvisbrain -d jarvis_alpha -v writer_pw="$PASSWORD" <<'EOF'
\set QUIET on
ALTER ROLE jarvis_alpha_writer WITH PASSWORD :'writer_pw';
\echo '✅ Password set for jarvis_alpha_writer'
EOF

echo "✅ Done. Verify connection with scripts/smoke_writer_role.sh"
