#!/usr/bin/env bash
# smoke_task_events_insert.sh — verify alpha_task_events INSERT + severity CHECK (TD-49)
# Runs on Brain only.

set -euo pipefail

if [[ "$(hostname -s)" != "jarvis-brain" ]]; then
  echo "❌ Must run on Brain (current host: $(hostname -s))" >&2
  exit 1
fi

PSQL="/opt/homebrew/Cellar/postgresql@16/16.13/bin/psql"

echo ""
echo "=== Smoke Test — alpha_task_events (severity column + CHECK) ==="
echo ""

delete_by_id() {
  local id="$1"
  "$PSQL" -X -U jarvisbrain -d jarvis_alpha -v ON_ERROR_STOP=1 -c \
    "DELETE FROM alpha_task_events WHERE id = '${id}'::uuid;"
}

insert_verify_delete() {
  local severity_val="$1"
  local detail="$2"
  local id
  id=$("$PSQL" -X -U jarvisbrain -d jarvis_alpha -tAc "
    WITH ins AS (
      INSERT INTO alpha_task_events (event_type, graph_id, step_id, message, severity)
      VALUES ('step_retrying', NULL, NULL, '${detail}', '${severity_val}')
      RETURNING id
    )
    SELECT id::text FROM ins;
  ")
  if [[ -z "${id// /}" ]]; then
    echo "❌ INSERT failed for severity=${severity_val}" >&2
    return 1
  fi
  id=$(echo "$id" | tr -d '[:space:]')
  echo "Inserted id=${id} (severity=${severity_val})"
  local cnt
  cnt=$("$PSQL" -X -U jarvisbrain -d jarvis_alpha -tAc \
    "SELECT count(*)::text FROM alpha_task_events WHERE id = '${id}'::uuid;")
  if [[ "$cnt" != "1" ]]; then
    echo "❌ Confirm failed: expected 1 row, got ${cnt}" >&2
    return 1
  fi
  delete_by_id "$id"
  echo "Deleted test row ${id}"
  echo ""
}

insert_verify_delete warning "smoke_task_events_insert: warning path"
insert_verify_delete critical "smoke_task_events_insert: critical path"

echo "TEST: legacy severity value 'high' must be REJECTED by CHECK constraint"
set +e
OUT=$("$PSQL" -X -U jarvisbrain -d jarvis_alpha -tAc "
  WITH ins AS (
    INSERT INTO alpha_task_events (event_type, graph_id, step_id, message, severity)
    VALUES ('step_retrying', NULL, NULL, 'smoke_task_events_insert: negative high', 'high')
    RETURNING id
  )
  SELECT id::text FROM ins;
" 2>&1)
RC=$?
set -e

if [[ "$RC" -eq 0 ]] && [[ -n "${OUT// /}" ]] && [[ "$OUT" =~ ^[a-f0-9-]{36}$ ]]; then
  echo "❌ FATAL: INSERT with severity='high' succeeded — schema may still use old CHECK" >&2
  delete_by_id "$(echo "$OUT" | tr -d '[:space:]')" || true
  exit 1
fi

echo "OK: severity='high' rejected (psql exit ${RC})"
echo ""

exit 0
