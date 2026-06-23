#!/usr/bin/env bash
# restore_drill_alpha.sh — DR-readiness drill: pull latest jarvis_alpha encrypted
# dump from Unraid, decrypt on Sandbox, restore into ephemeral OrbStack
# container, verify structure + row counts against live Brain reference.
#
# Runs on Sandbox. Deliberately independent of Brain so DR works even when
# Brain is down. Notifications and buddy_event are best-effort.
set -euo pipefail

# ---------- constants -----------------------------------------------------------
RUN_TS=$(date -u +%Y-%m-%d_%H%M%S)
HOST_SHORT=$(hostname -s)
CONTAINER="pg_drill_$$"
SECRETS_FILE="${HOME}/.secrets"
TMP_DIR="${HOME}/jarvis/tmp"
LOG_DIR="${HOME}/jarvis/logs"
TMP_DUMP="${TMP_DIR}/drill_${RUN_TS}.dump"
TMP_GPG="${TMP_DUMP}.gpg"
LOG="${LOG_DIR}/restore_drill.log"
REPORT_JSON="${LOG_DIR}/restore_drill_${RUN_TS}.json"
DRILL_DB="jarvis_alpha_drill"
IMAGE="pgvector/pgvector:pg16"

# Minimum public relation baseline. Exact relation count grows with normal
# migrations, so critical readiness is enforced through named table, row-count,
# FORCE RLS, and restore-error probes below.
MIN_PUBLIC_RELATIONS=105
EXPECTED_PRIVACY_TABLES=16
EXPECTED_PRIVACY_FORCE_RLS_TABLES=16
EXPECTED_MEMORY_FORCE_RLS_TABLES=6

# Tools
find_tool() {
    local name="$1"
    local found
    found=$(command -v "$name" 2>/dev/null || true)
    if [[ -n "$found" ]]; then
        printf '%s\n' "$found"
        return 0
    fi
    local candidate
    for candidate in \
        "/opt/homebrew/bin/${name}" \
        "/usr/local/bin/${name}" \
        "/usr/bin/${name}" \
        "/bin/${name}"; do
        if [[ -x "$candidate" ]]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

JQ=$(find_tool jq || true)
GPG=$(find_tool gpg || true)
DOCKER=$(find_tool docker || true)
SHA256=$(command -v shasum >/dev/null 2>&1 && echo "shasum -a 256" || echo "sha256sum")

mkdir -p "$TMP_DIR" "$LOG_DIR"
chmod 700 "$TMP_DIR" 2>/dev/null || true

# ---------- arg parse -----------------------------------------------------------
KEEP=false
INJECT_CORRUPT=false
for arg in "$@"; do
    case "$arg" in
        --keep) KEEP=true ;;
        --inject-corrupt) INJECT_CORRUPT=true ;;
        --help|-h)
            echo "Usage: $0 [--keep] [--inject-corrupt]"
            echo "  --keep            Do not tear down container/temp files (manual inspection)"
            echo "  --inject-corrupt  Truncate decrypted dump to 1KB before restore (FAIL-path drill)"
            exit 0
            ;;
        *) echo "unknown arg: $arg" >&2; exit 64 ;;
    esac
done

# ---------- logging helpers -----------------------------------------------------
log_json() {
    local line="$1"
    printf '%s\n' "$line" >> "$LOG"
    printf '%s\n' "$line"
}

make_event() {
    # make_event <event_name> [k=v ...]
    local event="$1"; shift
    local ts; ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    local extra=""
    for kv in "$@"; do
        local k="${kv%%=*}"; local v="${kv#*=}"
        extra+=",\"${k}\":\"${v}\""
    done
    printf '{"event":"%s","ts":"%s","run_id":"%s","host":"%s"%s}' \
        "$event" "$ts" "$RUN_TS" "$HOST_SHORT" "$extra"
}

# ---------- cleanup trap --------------------------------------------------------
cleanup() {
    local exit_code=$?
    if [[ "$KEEP" == "true" ]]; then
        log_json "$(make_event cleanup_skipped reason=keep_flag container="$CONTAINER" tmp_dump="$TMP_DUMP")"
        exit "$exit_code"
    fi
    "$DOCKER" rm -f "$CONTAINER" >/dev/null 2>&1 || true
    rm -f "$TMP_DUMP" "$TMP_GPG" 2>/dev/null || true
    log_json "$(make_event cleanup_done exit_code="$exit_code")"
    exit "$exit_code"
}
trap cleanup EXIT

# ---------- secrets -------------------------------------------------------------
if [[ ! -f "$SECRETS_FILE" ]]; then
    log_json "$(make_event fatal reason=no_secrets_file path="$SECRETS_FILE")"
    exit 2
fi

read_secret() {
    awk -F= -v k="$1" '$1==k{sub(/^[^=]+=/,""); print; exit}' "$SECRETS_FILE"
}

RESTORE_SSH_HOST=$(read_secret RESTORE_SSH_HOST)
RESTORE_SSH_USER=$(read_secret RESTORE_SSH_USER)
RESTORE_SSH_KEY=$(read_secret RESTORE_SSH_KEY)
RESTORE_SSH_SOURCE_DIR=$(read_secret RESTORE_SSH_SOURCE_DIR)
GATEWAY_TOKEN=$(read_secret GATEWAY_TOKEN)

if [[ -z "$RESTORE_SSH_HOST" || -z "$RESTORE_SSH_KEY" || -z "$RESTORE_SSH_SOURCE_DIR" ]]; then
    log_json "$(make_event fatal reason=missing_restore_ssh_config)"
    exit 2
fi

# ---------- notification helpers (best-effort, never block drill) ---------------
mm_notify() {
    local severity="$1"; local title="$2"; local message="$3"
    local gateway_url="${ALPHA_GATEWAY_URL:-${GATEWAY_URL:-https://jarvis-gateway.tail40ed36.ts.net:8283}}"
    if [[ -z "${GATEWAY_TOKEN:-}" ]]; then
        log_json "$(make_event mm_notify_skipped reason=no_gateway_token)"
        return 0
    fi
    if [[ -z "$JQ" ]]; then
        log_json "$(make_event mm_notify_skipped reason=no_jq)"
        return 0
    fi
    local payload
    if ! payload=$("$JQ" -nc \
            --arg title "$title" --arg message "$message" \
            --arg severity "$severity" --arg source "alpha" \
            --arg channel_key "alpha_events" \
            '{title:$title, message:$message, severity:$severity, source:$source, channel_key:$channel_key}'); then
        log_json "$(make_event mm_notify_failed reason=jq_build)"
        return 0
    fi
    local resp_tmp="/tmp/mm_notify_resp.$$"
    local http_code
    http_code=$(curl -sS -o "$resp_tmp" -w "%{http_code}" --max-time 8 \
        -X POST "${gateway_url}/v1/notify/mattermost" \
        -H "Authorization: Bearer ${GATEWAY_TOKEN}" \
        -H "Content-Type: application/json" \
        -H "X-JARVIS-Idempotency-Key: drill-${RUN_TS}" \
        -d "$payload" 2>/dev/null || echo "000")
    rm -f "$resp_tmp"
    if [[ "$http_code" =~ ^2 ]]; then
        log_json "$(make_event mm_notify_sent severity="$severity" http_code="$http_code")"
    else
        log_json "$(make_event mm_notify_failed severity="$severity" http_code="$http_code")"
    fi
    return 0
}

buddy_event() {
    local event_type="$1"; local title="$2"; local body="$3"; local priority="$4"
    if [[ -z "$JQ" ]]; then
        log_json "$(make_event buddy_event_skipped reason=no_jq)"
        return 0
    fi
    local payload
    payload=$("$JQ" -nc --arg run_id "$RUN_TS" --arg host "$HOST_SHORT" \
        '{run_id:$run_id, host:$host, source:"restore_drill_alpha"}')
    local remote_psql
    remote_psql='set -a; source ~/jarvis/.secrets; set +a; PGPASSWORD="$POSTGRES_PASSWORD" /opt/homebrew/Cellar/postgresql@16/16.13/bin/psql -h 127.0.0.1 -U jarvisbrain -d jarvis_alpha -v ON_ERROR_STOP=0 -q'
    # Build SQL on stdin to avoid nested -c quoting; $..$ dollar-quoting handles
    # any single quotes/special chars in title/body.
    if ! printf "INSERT INTO alpha_buddy_events (event_type, title, body, priority, source, payload) VALUES ('%s', \$tt\$%s\$tt\$, \$bb\$%s\$bb\$, %s, 'restore_drill_alpha', '%s'::jsonb);\n" \
            "$event_type" "$title" "$body" "$priority" "$payload" \
        | ssh -o BatchMode=yes -o ConnectTimeout=3 jarvisbrain@jarvis-brain \
            "$remote_psql" \
            >/dev/null 2>&1; then
        log_json "$(make_event buddy_event_failed event_type="$event_type" reason=ssh_or_psql)"
    fi
    return 0
}

# ---------- prelaunch checks ----------------------------------------------------
log_json "$(make_event run_start dbs=jarvis_alpha image="$IMAGE" container="$CONTAINER" dry_run=false)"

if [[ -z "$DOCKER" ]]; then
    log_json "$(make_event fatal reason=no_docker_bin)"
    exit 4
fi
if ! "$DOCKER" ps >/dev/null 2>&1; then
    log_json "$(make_event fatal reason=docker_daemon_down)"
    mm_notify critical "Restore drill FAILED" "Docker daemon down on ${HOST_SHORT}"
    buddy_event alert "Restore drill failed" "reason=docker_daemon_down run=${RUN_TS}" 3
    exit 4
fi
if [[ -z "$GPG" ]]; then
    log_json "$(make_event fatal reason=no_gpg_bin)"
    exit 3
fi
if [[ -z "$JQ" ]]; then
    log_json "$(make_event warn reason=no_jq_notifications_degraded)"
fi

# ---------- 1. find + pull latest dump from Unraid ------------------------------
PULL_T0=$(date +%s)
LATEST=$(ssh -i "$RESTORE_SSH_KEY" -o BatchMode=yes -o ConnectTimeout=10 \
    "${RESTORE_SSH_USER}@${RESTORE_SSH_HOST}" \
    "ls -t ${RESTORE_SSH_SOURCE_DIR}/jarvis_alpha_*.dump.gpg | head -1" 2>/dev/null || true)
if [[ -z "$LATEST" ]]; then
    log_json "$(make_event fatal reason=no_dump_found_on_unraid)"
    mm_notify critical "Restore drill FAILED" "No jarvis_alpha dump found on Unraid"
    buddy_event alert "Restore drill failed" "reason=no_dump_found run=${RUN_TS}" 3
    exit 2
fi
log_json "$(make_event pull_start latest="$(basename "$LATEST")")"

if ! scp -i "$RESTORE_SSH_KEY" -o BatchMode=yes -q \
        "${RESTORE_SSH_USER}@${RESTORE_SSH_HOST}:${LATEST}" "$TMP_GPG"; then
    log_json "$(make_event fatal reason=scp_failed remote_path="$LATEST")"
    mm_notify critical "Restore drill FAILED" "scp pull failed from Unraid: $(basename "$LATEST")"
    buddy_event alert "Restore drill failed" "reason=scp_failed run=${RUN_TS}" 3
    exit 2
fi
chmod 600 "$TMP_GPG"
PULL_BYTES=$(stat -f '%z' "$TMP_GPG" 2>/dev/null || stat -c '%s' "$TMP_GPG")
PULL_DURATION=$(( $(date +%s) - PULL_T0 ))
log_json "$(make_event pull_complete bytes="$PULL_BYTES" duration_s="$PULL_DURATION")"

# ---------- 2. decrypt ----------------------------------------------------------
DEC_T0=$(date +%s)
if ! "$GPG" --decrypt --batch --quiet --yes --passphrase-fd 3 \
        --output "$TMP_DUMP" "$TMP_GPG" \
        3< <(awk -F= '/^BACKUP_GPG_PASSPHRASE=/{sub(/^[^=]+=/,"");print;exit}' "$SECRETS_FILE"); then
    log_json "$(make_event fatal reason=gpg_decrypt_failed)"
    mm_notify critical "Restore drill FAILED" "GPG decrypt failed for $(basename "$LATEST")"
    buddy_event alert "Restore drill failed" "reason=gpg_decrypt_failed run=${RUN_TS}" 3
    exit 3
fi
chmod 600 "$TMP_DUMP"
DEC_BYTES=$(stat -f '%z' "$TMP_DUMP" 2>/dev/null || stat -c '%s' "$TMP_DUMP")
DEC_DURATION=$(( $(date +%s) - DEC_T0 ))
log_json "$(make_event decrypt_complete bytes="$DEC_BYTES" duration_s="$DEC_DURATION")"

# Optional: inject corruption to verify drill catches bad backups.
if [[ "$INJECT_CORRUPT" == "true" ]]; then
    dd if="$TMP_DUMP" of="${TMP_DUMP}.tmp" bs=1 count=1024 status=none
    mv "${TMP_DUMP}.tmp" "$TMP_DUMP"
    DEC_BYTES=$(stat -f '%z' "$TMP_DUMP" 2>/dev/null || stat -c '%s' "$TMP_DUMP")
    log_json "$(make_event corruption_injected new_bytes="$DEC_BYTES")"
fi

# ---------- 3. spin ephemeral pgvector container --------------------------------
SPIN_T0=$(date +%s)
if ! "$DOCKER" image inspect "$IMAGE" >/dev/null 2>&1; then
    log_json "$(make_event image_pull_start image="$IMAGE")"
    if ! "$DOCKER" pull "$IMAGE" >/dev/null 2>&1; then
        log_json "$(make_event fatal reason=image_pull_failed image="$IMAGE")"
        mm_notify critical "Restore drill FAILED" "Failed to pull $IMAGE"
        buddy_event alert "Restore drill failed" "reason=image_pull_failed run=${RUN_TS}" 3
        exit 4
    fi
    log_json "$(make_event image_pull_complete image="$IMAGE")"
fi

if ! "$DOCKER" run -d --name "$CONTAINER" \
        -e POSTGRES_PASSWORD=drill \
        -e POSTGRES_DB="$DRILL_DB" \
        "$IMAGE" >/dev/null 2>&1; then
    log_json "$(make_event fatal reason=container_start_failed)"
    mm_notify critical "Restore drill FAILED" "docker run failed"
    buddy_event alert "Restore drill failed" "reason=container_start_failed run=${RUN_TS}" 3
    exit 4
fi

# The official Postgres image starts a temporary server during initdb, shuts it
# down, then starts the final server. pg_isready and SELECT 1 can briefly pass
# during the temporary phase, which races pg_restore into "server is shutting
# down". Wait for the final init marker before trusting readiness.
INIT_COMPLETE=false
for i in $(seq 1 60); do
    if "$DOCKER" logs "$CONTAINER" 2>&1 | grep -q 'PostgreSQL init process complete'; then
        INIT_COMPLETE=true; break
    fi
    sleep 1
done
if [[ "$INIT_COMPLETE" != "true" ]]; then
    log_json "$(make_event fatal reason=container_init_not_complete_60s)"
    mm_notify critical "Restore drill FAILED" "container init never completed"
    buddy_event alert "Restore drill failed" "reason=container_init_not_complete run=${RUN_TS}" 3
    exit 4
fi
log_json "$(make_event container_init_complete container="$CONTAINER")"

# Wait for final ready (max 30s). Require pg_isready AND a real SELECT 1.
READY=false
for i in $(seq 1 30); do
    if "$DOCKER" exec "$CONTAINER" pg_isready -U postgres >/dev/null 2>&1 \
        && "$DOCKER" exec "$CONTAINER" psql -U postgres -d postgres -tAc 'SELECT 1' >/dev/null 2>&1; then
        READY=true; break
    fi
    sleep 1
done
if [[ "$READY" != "true" ]]; then
    log_json "$(make_event fatal reason=container_not_ready_30s)"
    mm_notify critical "Restore drill FAILED" "container never became ready"
    buddy_event alert "Restore drill failed" "reason=container_not_ready run=${RUN_TS}" 3
    exit 4
fi
SPIN_DURATION=$(( $(date +%s) - SPIN_T0 ))
log_json "$(make_event container_ready container="$CONTAINER" duration_s="$SPIN_DURATION")"

# ---------- 4. pre-create extensions, restore -----------------------------------
RESTORE_T0=$(date +%s)
"$DOCKER" exec "$CONTAINER" psql -U postgres -d "$DRILL_DB" -v ON_ERROR_STOP=0 -c \
    "CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pgcrypto;" \
    >/dev/null 2>&1 || true

if ! "$DOCKER" cp "$TMP_DUMP" "${CONTAINER}:/tmp/drill.dump" 2>/dev/null; then
    log_json "$(make_event fatal reason=docker_cp_failed)"
    mm_notify critical "Restore drill FAILED" "docker cp failed"
    buddy_event alert "Restore drill failed" "reason=docker_cp_failed run=${RUN_TS}" 3
    exit 5
fi

# pg_restore stderr → log + count errors
RESTORE_ERR_FILE="${LOG_DIR}/restore_drill_${RUN_TS}.stderr"
set +e
"$DOCKER" exec "$CONTAINER" pg_restore \
    --no-owner --no-privileges --no-acl \
    -U postgres -d "$DRILL_DB" /tmp/drill.dump \
    > /dev/null 2> "$RESTORE_ERR_FILE"
RESTORE_RC=$?
set -e
RESTORE_DURATION=$(( $(date +%s) - RESTORE_T0 ))

# count ERROR lines in stderr (warnings start with "pg_restore: warning").
# Note: grep -c exits 1 when count=0; use || true so the count value (always
# printed by -c) is what we capture — not concat'd with a fallback "0".
RESTORE_ERR_COUNT=$(grep -c 'pg_restore: error' "$RESTORE_ERR_FILE" 2>/dev/null || true)
RESTORE_ERR_COUNT=${RESTORE_ERR_COUNT:-0}
# count pg_restore errors specifically tied to pgaudit (extension we expect to
# be missing in pgvector image). Bind the error AND the pgaudit mention together
# by matching error lines that include pgaudit, plus the standalone DETAIL/HINT
# lines that immediately follow a pgaudit error.
PGAUDIT_ERR_COUNT=$(grep -c -E 'pg_restore: error.*pgaudit|extension "pgaudit"' "$RESTORE_ERR_FILE" 2>/dev/null || true)
PGAUDIT_ERR_COUNT=${PGAUDIT_ERR_COUNT:-0}
log_json "$(make_event restore_complete rc="$RESTORE_RC" duration_s="$RESTORE_DURATION" err_count="$RESTORE_ERR_COUNT" pgaudit_err_count="$PGAUDIT_ERR_COUNT")"

# acceptable: rc may be 1 IF only the pgaudit error is present
RESTORE_PASS=true
if [[ "$RESTORE_RC" -ne 0 ]]; then
    if [[ "$RESTORE_ERR_COUNT" -gt "$PGAUDIT_ERR_COUNT" ]]; then
        RESTORE_PASS=false
    fi
fi

# ---------- 5. verify -----------------------------------------------------------
psqlc() {
    "$DOCKER" exec "$CONTAINER" psql -U postgres -d "$DRILL_DB" -tAc "$1" 2>/dev/null | tr -d ' \n'
}

TABLE_COUNT=$(psqlc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
[[ -z "$TABLE_COUNT" ]] && TABLE_COUNT=0

ROWS_BUDDY=$(psqlc "SELECT count(*) FROM alpha_buddy_events" 2>/dev/null || echo ERR)
ROWS_REQLOG=$(psqlc "SELECT count(*) FROM jarvis_request_log" 2>/dev/null || echo ERR)
ROWS_APPROVAL=$(psqlc "SELECT count(*) FROM alpha_approval_queue" 2>/dev/null || echo ERR)
ROWS_NODES=$(psqlc "SELECT count(*) FROM alpha_node_registry" 2>/dev/null || echo ERR)
HAS_CONVMEM=$(psqlc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_name='alpha_conversation_memory'")
HAS_SEMANTIC_MEMORY=$(psqlc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_name='alpha_semantic_memory'")
HAS_MEMORY_PROPOSALS=$(psqlc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_name='alpha_memory_consolidation_proposals'")
HAS_MEMORY_LEDGER=$(psqlc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_name='alpha_memory_consolidation_execution_ledger'")
MEMORY_FORCE_RLS=$(psqlc "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname='public' AND c.relkind='r' AND c.relname IN ('alpha_semantic_memory','alpha_conversation_memory','alpha_buddy_events','alpha_buddy_events_archive','alpha_memory_consolidation_proposals','alpha_memory_consolidation_execution_ledger') AND c.relrowsecurity AND c.relforcerowsecurity" 2>/dev/null || echo ERR)
PRIVACY_TABLES=$(psqlc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_name LIKE 'alpha_privacy_%'" 2>/dev/null || echo ERR)
PRIVACY_FORCE_RLS=$(psqlc "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname='public' AND c.relkind='r' AND c.relname LIKE 'alpha_privacy_%' AND c.relrowsecurity AND c.relforcerowsecurity" 2>/dev/null || echo ERR)

VERIFY_PASS=true
FAIL_REASONS=""
add_fail() { FAIL_REASONS="${FAIL_REASONS}${FAIL_REASONS:+;}$1"; VERIFY_PASS=false; }

# table count is a lower-bound sanity check. Named critical table probes below
# are the authoritative readiness checks.
if ! [[ "$TABLE_COUNT" =~ ^[0-9]+$ ]] || [[ "$TABLE_COUNT" -lt "$MIN_PUBLIC_RELATIONS" ]]; then
    add_fail "table_count=${TABLE_COUNT}_minimum=${MIN_PUBLIC_RELATIONS}"
fi
[[ "$ROWS_BUDDY" == "ERR" || "$ROWS_BUDDY" -lt 1 ]] && add_fail "alpha_buddy_events_${ROWS_BUDDY}"
[[ "$ROWS_REQLOG" == "ERR" || "$ROWS_REQLOG" -lt 1 ]] && add_fail "jarvis_request_log_${ROWS_REQLOG}"
[[ "$ROWS_APPROVAL" == "ERR" ]] && add_fail "alpha_approval_queue_missing"
[[ "$ROWS_NODES" == "ERR" || "$ROWS_NODES" -lt 1 ]] && add_fail "alpha_node_registry_${ROWS_NODES}"
[[ "$HAS_CONVMEM" != "1" ]] && add_fail "alpha_conversation_memory_table_missing"
[[ "$HAS_SEMANTIC_MEMORY" != "1" ]] && add_fail "alpha_semantic_memory_table_missing"
[[ "$HAS_MEMORY_PROPOSALS" != "1" ]] && add_fail "alpha_memory_consolidation_proposals_table_missing"
[[ "$HAS_MEMORY_LEDGER" != "1" ]] && add_fail "alpha_memory_consolidation_execution_ledger_table_missing"
if ! [[ "$MEMORY_FORCE_RLS" =~ ^[0-9]+$ ]] || [[ "$MEMORY_FORCE_RLS" -lt "$EXPECTED_MEMORY_FORCE_RLS_TABLES" ]]; then
    add_fail "memory_force_rls_${MEMORY_FORCE_RLS}_expected_${EXPECTED_MEMORY_FORCE_RLS_TABLES}"
fi
if ! [[ "$PRIVACY_TABLES" =~ ^[0-9]+$ ]] || [[ "$PRIVACY_TABLES" -lt "$EXPECTED_PRIVACY_TABLES" ]]; then
    add_fail "privacy_tables_${PRIVACY_TABLES}_expected_${EXPECTED_PRIVACY_TABLES}"
fi
if ! [[ "$PRIVACY_FORCE_RLS" =~ ^[0-9]+$ ]] || [[ "$PRIVACY_FORCE_RLS" -lt "$EXPECTED_PRIVACY_FORCE_RLS_TABLES" ]]; then
    add_fail "privacy_force_rls_${PRIVACY_FORCE_RLS}_expected_${EXPECTED_PRIVACY_FORCE_RLS_TABLES}"
fi

if [[ "$RESTORE_PASS" != "true" ]]; then
    add_fail "pg_restore_errors=${RESTORE_ERR_COUNT}_pgaudit_only=${PGAUDIT_ERR_COUNT}"
fi

# ---------- 6. emit drill report JSON ------------------------------------------
DRILL_STATUS="pass"
[[ "$VERIFY_PASS" == "true" ]] || DRILL_STATUS="fail"

if [[ -n "$JQ" ]]; then
    "$JQ" -nc \
        --arg run_id "$RUN_TS" \
        --arg host "$HOST_SHORT" \
        --arg status "$DRILL_STATUS" \
        --arg source_dump "$(basename "$LATEST")" \
        --arg image "$IMAGE" \
        --arg container "$CONTAINER" \
        --argjson pull_bytes "$PULL_BYTES" \
        --argjson dec_bytes "$DEC_BYTES" \
        --argjson restore_rc "$RESTORE_RC" \
        --argjson restore_err "$RESTORE_ERR_COUNT" \
        --argjson pgaudit_err "$PGAUDIT_ERR_COUNT" \
        --argjson table_count "$TABLE_COUNT" \
        --argjson min_tables "$MIN_PUBLIC_RELATIONS" \
        --arg fail_reasons "$FAIL_REASONS" \
        --arg rows_buddy "$ROWS_BUDDY" \
        --arg rows_reqlog "$ROWS_REQLOG" \
        --arg rows_approval "$ROWS_APPROVAL" \
        --arg rows_nodes "$ROWS_NODES" \
        --arg has_convmem "$HAS_CONVMEM" \
        --arg has_semantic_memory "$HAS_SEMANTIC_MEMORY" \
        --arg has_memory_proposals "$HAS_MEMORY_PROPOSALS" \
        --arg has_memory_ledger "$HAS_MEMORY_LEDGER" \
        --arg memory_force_rls "$MEMORY_FORCE_RLS" \
        --arg privacy_tables "$PRIVACY_TABLES" \
        --arg privacy_force_rls "$PRIVACY_FORCE_RLS" \
        '{
            run_id:$run_id, host:$host, status:$status,
            source_dump:$source_dump, image:$image, container:$container,
            pull_bytes:$pull_bytes, decrypted_bytes:$dec_bytes,
            restore_rc:$restore_rc, restore_err_count:$restore_err, pgaudit_err_count:$pgaudit_err,
            table_count:$table_count,
            minimum_table_count:$min_tables,
            ref_table_count:$min_tables,
            row_counts:{
                alpha_buddy_events:$rows_buddy,
                jarvis_request_log:$rows_reqlog,
                alpha_approval_queue:$rows_approval,
                alpha_node_registry:$rows_nodes,
                alpha_conversation_memory_table_present:$has_convmem,
                alpha_semantic_memory_table_present:$has_semantic_memory,
                alpha_memory_consolidation_proposals_table_present:$has_memory_proposals,
                alpha_memory_consolidation_execution_ledger_table_present:$has_memory_ledger,
                alpha_memory_force_rls_tables:$memory_force_rls,
                alpha_privacy_tables:$privacy_tables,
                alpha_privacy_force_rls_tables:$privacy_force_rls
            },
            fail_reasons:$fail_reasons
        }' > "$REPORT_JSON"
    log_json "$(make_event report_written path="$REPORT_JSON")"
fi

# ---------- 7. notify -----------------------------------------------------------
if [[ "$DRILL_STATUS" == "pass" ]]; then
    msg="Drill ${RUN_TS} · source ${LATEST##*/} · tables=${TABLE_COUNT} min=${MIN_PUBLIC_RELATIONS} · memory_force_rls=${MEMORY_FORCE_RLS}/${EXPECTED_MEMORY_FORCE_RLS_TABLES} · privacy=${PRIVACY_TABLES}/${EXPECTED_PRIVACY_TABLES} force_rls=${PRIVACY_FORCE_RLS}/${EXPECTED_PRIVACY_FORCE_RLS_TABLES} · rows: buddy=${ROWS_BUDDY} reqlog=${ROWS_REQLOG} approval=${ROWS_APPROVAL} nodes=${ROWS_NODES}"
    mm_notify info "Restore drill PASSED" "$msg"
    buddy_event system "Restore drill passed" "tables=${TABLE_COUNT} run=${RUN_TS}" 1
    log_json "$(make_event run_complete status=pass)"
else
    msg="Drill ${RUN_TS} FAILED · source ${LATEST##*/} · reasons: ${FAIL_REASONS} · report ${REPORT_JSON}"
    mm_notify critical "Restore drill FAILED" "$msg"
    buddy_event alert "Restore drill failed" "${FAIL_REASONS} run=${RUN_TS}" 3
    log_json "$(make_event run_complete status=fail fail_reasons="$FAIL_REASONS")"
fi

# ---------- 8. exit -------------------------------------------------------------
if [[ "$DRILL_STATUS" == "pass" ]]; then
    exit 0
else
    exit 1
fi
