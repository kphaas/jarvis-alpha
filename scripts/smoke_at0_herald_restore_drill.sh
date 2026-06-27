#!/usr/bin/env bash
# Focused Herald restore drill. Dumps Herald mail/social/audit/monitor tables from
# jarvis_alpha, restores them into a scratch database, and compares row counts.

set -euo pipefail

RUN_TS="$(date -u +%Y%m%d_%H%M%S)"
REPORT_DATE="$(date -u +%Y-%m-%d)"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SECRETS_FILE="${SECRETS_FILE:-${HOME}/jarvis/.secrets}"
SOURCE_DB="${HERALD_DRILL_SOURCE_DB:-jarvis_alpha}"
DRILL_DB="${HERALD_DRILL_DB:-jarvis_alpha_herald_drill_${RUN_TS}_$$}"
TMP_ROOT="${TMPDIR:-/tmp}"
TMP_DIR="${TMP_ROOT%/}/at0_herald_restore_drill_${RUN_TS}_$$"
SCHEMA_SQL="${TMP_DIR}/herald_schema.sql"
DATA_DUMP="${TMP_DIR}/herald_data.dump"
REPORT_PATH="${HERALD_DRILL_REPORT_PATH:-${REPO_ROOT}/docs/reports/herald_restore_drill_${REPORT_DATE}.md}"

TABLES=(
  public.alpha_at0_mail_scan_runs
  public.alpha_at0_mail_messages
  public.alpha_at0_mail_draft_proposals
  public.alpha_at0_mail_send_events
  public.alpha_at0_mail_graph_health
  public.alpha_herald_social_platform_profiles
  public.alpha_herald_social_draft_requests
  public.alpha_herald_social_draft_variants
  public.alpha_herald_social_draft_events
  public.alpha_herald_social_engagement_items
)

PSQL="${PSQL:-/opt/homebrew/Cellar/postgresql@16/16.13/bin/psql}"
PG_DUMP="${PG_DUMP:-/opt/homebrew/Cellar/postgresql@16/16.13/bin/pg_dump}"
PG_RESTORE="${PG_RESTORE:-/opt/homebrew/Cellar/postgresql@16/16.13/bin/pg_restore}"

if [ ! -x "$PSQL" ]; then PSQL="$(command -v psql)"; fi
if [ ! -x "$PG_DUMP" ]; then PG_DUMP="$(command -v pg_dump)"; fi
if [ ! -x "$PG_RESTORE" ]; then PG_RESTORE="$(command -v pg_restore)"; fi

mkdir -p "$TMP_DIR" "$(dirname "$REPORT_PATH")"
chmod 700 "$TMP_DIR" 2>/dev/null || true

cleanup() {
  local exit_code=$?
  if [[ "$DRILL_DB" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
    PGPASSWORD="${POSTGRES_PASSWORD:-}" "$PSQL" \
      -h "${PGHOST:-127.0.0.1}" -U "${PGUSER:-jarvisbrain}" -d postgres \
      -v ON_ERROR_STOP=0 -qAt \
      -c "DROP DATABASE IF EXISTS ${DRILL_DB};" >/dev/null 2>&1 || true
  fi
  rm -rf "$TMP_DIR"
  exit "$exit_code"
}
trap cleanup EXIT

if [ ! -f "$SECRETS_FILE" ]; then
  echo "FAIL: secrets file missing: $SECRETS_FILE" >&2
  exit 2
fi

set -a
# shellcheck disable=SC1090
source "$SECRETS_FILE"
set +a

if [ -z "${POSTGRES_PASSWORD:-}" ]; then
  echo "FAIL: POSTGRES_PASSWORD missing from $SECRETS_FILE" >&2
  exit 2
fi

export PGHOST="${PGHOST:-127.0.0.1}"
export PGUSER="${PGUSER:-jarvisbrain}"
export PGPASSWORD="${PGPASSWORD:-$POSTGRES_PASSWORD}"

if [[ ! "$DRILL_DB" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
  echo "FAIL: unsafe scratch database name: $DRILL_DB" >&2
  exit 2
fi

psql_scalar() {
  local db="$1"
  local sql="$2"
  "$PSQL" -h "$PGHOST" -U "$PGUSER" -d "$db" -v ON_ERROR_STOP=1 -qAt -c "$sql"
}

psql_exec() {
  local db="$1"
  local sql="$2"
  "$PSQL" -h "$PGHOST" -U "$PGUSER" -d "$db" -v ON_ERROR_STOP=1 -q -c "$sql" >/dev/null
}

table_args=()
for table in "${TABLES[@]}"; do
  table_args+=(--table "$table")
done

for table in "${TABLES[@]}"; do
  exists="$(psql_scalar "$SOURCE_DB" "SELECT to_regclass('$table') IS NOT NULL;")"
  if [ "$exists" != "t" ]; then
    echo "FAIL: required table missing in $SOURCE_DB: $table" >&2
    exit 1
  fi
done

"$PG_DUMP" \
  --schema-only \
  --no-owner \
  --no-acl \
  --dbname "$SOURCE_DB" \
  "${table_args[@]}" \
  --file "$SCHEMA_SQL"

if ! grep -Eq "CREATE (OR REPLACE )?FUNCTION public\\.alpha_at0_mail_send_events_immutable" "$SCHEMA_SQL"; then
  FUNC_SQL="${TMP_DIR}/send_events_function.sql"
  cat >"$FUNC_SQL" <<'SQL'
CREATE OR REPLACE FUNCTION public.alpha_at0_mail_send_events_immutable()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'pg_catalog', 'public'
AS $$
BEGIN
    RAISE EXCEPTION 'alpha_at0_mail_send_events is append-only';
END;
$$;
SQL
  cat "$FUNC_SQL" "$SCHEMA_SQL" >"${SCHEMA_SQL}.with_function"
  mv "${SCHEMA_SQL}.with_function" "$SCHEMA_SQL"
fi

if ! grep -Eq "CREATE (OR REPLACE )?FUNCTION public\\.alpha_herald_social_draft_events_immutable" "$SCHEMA_SQL"; then
  FUNC_SQL="${TMP_DIR}/social_draft_events_function.sql"
  cat >"$FUNC_SQL" <<'SQL'
CREATE OR REPLACE FUNCTION public.alpha_herald_social_draft_events_immutable()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'pg_catalog', 'public'
AS $$
BEGIN
    RAISE EXCEPTION 'alpha_herald_social_draft_events is append-only';
END;
$$;
SQL
  cat "$FUNC_SQL" "$SCHEMA_SQL" >"${SCHEMA_SQL}.with_function"
  mv "${SCHEMA_SQL}.with_function" "$SCHEMA_SQL"
fi

"$PG_DUMP" \
  --data-only \
  --format=custom \
  --no-owner \
  --no-acl \
  --dbname "$SOURCE_DB" \
  "${table_args[@]}" \
  --file "$DATA_DUMP"
chmod 600 "$SCHEMA_SQL" "$DATA_DUMP" 2>/dev/null || true

psql_exec postgres "DROP DATABASE IF EXISTS ${DRILL_DB};"
psql_exec postgres "CREATE DATABASE ${DRILL_DB};"
psql_exec "$DRILL_DB" "CREATE EXTENSION IF NOT EXISTS pgcrypto;"
"$PSQL" -h "$PGHOST" -U "$PGUSER" -d "$DRILL_DB" -v ON_ERROR_STOP=1 -q -f "$SCHEMA_SQL" >/dev/null
"$PG_RESTORE" --exit-on-error --dbname "$DRILL_DB" "$DATA_DUMP" >/dev/null

schema_count="$(psql_scalar "$DRILL_DB" "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' AND (table_name LIKE 'alpha_at0_mail_%' OR table_name LIKE 'alpha_herald_social_%');")"
trigger_count="$(psql_scalar "$DRILL_DB" "SELECT count(*) FROM pg_trigger WHERE tgname IN ('trg_alpha_at0_mail_send_events_immutable', 'trg_alpha_herald_social_draft_events_immutable');")"

status="PASS"
rows_md=""
total_live=0
total_restored=0
for table in "${TABLES[@]}"; do
  live_count="$(psql_scalar "$SOURCE_DB" "SELECT count(*) FROM $table;")"
  restored_count="$(psql_scalar "$DRILL_DB" "SELECT count(*) FROM $table;")"
  total_live=$((total_live + live_count))
  total_restored=$((total_restored + restored_count))
  match="yes"
  if [ "$live_count" != "$restored_count" ]; then
    status="FAIL"
    match="no"
  fi
  rows_md+="| \`$table\` | $live_count | $restored_count | $match |"$'\n'
done

if [ "$schema_count" -lt "${#TABLES[@]}" ] || [ "$trigger_count" -lt 2 ]; then
  status="FAIL"
fi

rows_md_trimmed="${rows_md%$'\n'}"

cat >"$REPORT_PATH" <<EOF
# Herald Restore Drill — ${REPORT_DATE}

| Field | Value |
|---|---|
| Status | ${status} |
| Run timestamp | ${RUN_TS} UTC |
| Source database | ${SOURCE_DB} |
| Scratch database | ${DRILL_DB} (dropped after verification) |
| Tables verified | ${#TABLES[@]} |
| Restored Herald tables found | ${schema_count} |
| Append-only triggers found | ${trigger_count} |
| Live rows | ${total_live} |
| Restored rows | ${total_restored} |

## Table Counts

| Table | Live rows | Restored rows | Match |
|---|---:|---:|---|
${rows_md_trimmed}

## Evidence Notes

- Drill restored Herald mail intake, social draft outbox, append-only audit, and Graph health monitor tables into an isolated scratch database.
- Report intentionally records metadata and row counts only. It does not include email body previews, reply/social draft text, Graph tokens, platform tokens, or secrets.
- Scratch dump files were mode 600 and removed after the drill.
EOF

if [ "$status" != "PASS" ]; then
  echo "FAIL Herald restore drill: report=$REPORT_PATH" >&2
  exit 1
fi

echo "PASS Herald restore drill: tables=${#TABLES[@]} rows=${total_restored} report=$REPORT_PATH"
