#!/bin/bash
# pg_backup_alpha.sh — Encrypted Postgres backup: pg_dump → gpg → scp → manifest → retention
#
# Pipeline:
#   pg_dump --format=custom <db>
#     | gpg --symmetric --cipher-algo AES256 --batch --passphrase-fd 3
#     → /tmp/<db>_<UTC-TS>.dump.gpg
#     → scp to <REMOTE>:<TARGET_DIR>/dumps/<file>.partial
#     → ssh remote: chmod 600 + sha256 verify + atomic mv → final
#   manifest JSON written locally + scp'd to <TARGET_DIR>/manifests/
#   retention: keep last 30d + first-of-month forever
#
# Pivoted from SMB to SSH 2026-05-27 (Session 1 handoff). See preflight_brain_backup.sh.
#
# Lock: mkdir-based (macOS lacks flock). Same atomicity guarantee on POSIX.
# Secrets: BACKUP_GPG_PASSPHRASE passed to gpg via fd 3 ONLY — never argv, never env-after-use.
#
# Usage:
#   bash ~/jarvis-alpha/scripts/pg_backup_alpha.sh              # full run
#   bash ~/jarvis-alpha/scripts/pg_backup_alpha.sh --dry-run    # schema-only + no scp
#   bash ~/jarvis-alpha/scripts/pg_backup_alpha.sh --db jarvis_alpha  # one DB
#
# Exit codes:
#   0  success (or lock-held skip)
#   1  preflight or secrets failed
#   2  pg_dump failed
#   3  gpg encrypt failed
#   4  scp transfer / atomic rename failed
#   5  remote sha256 mismatch / verify failed
#   6  manifest write/transfer failed
#   (retention failures are logged but do not change exit code)

set -euo pipefail
# NEVER enable `set -x` — would expose secrets path/content.

# ─── Paths (absolute, no PATH dependence) ──────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PG_DUMP=/opt/homebrew/Cellar/postgresql@16/16.13/bin/pg_dump
PSQL=/opt/homebrew/Cellar/postgresql@16/16.13/bin/psql
GPG=/opt/homebrew/bin/gpg
JQ=/usr/bin/jq
SHASUM=/usr/bin/shasum
PREFLIGHT="$SCRIPT_DIR/preflight_brain_backup.sh"

SECRETS_FILE="$HOME/jarvis/.secrets"
LOG_DIR="$HOME/jarvis/logs"
LOG_FILE="$LOG_DIR/pg_backup.log"
MANIFEST_DIR="$LOG_DIR/manifests"
TMP_DIR="/tmp"
LOCK_DIR="/tmp/pg_backup_alpha.lock"

# Locked decision #1
DBS=(jarvis_alpha temporal temporal_visibility)

# ─── Args ──────────────────────────────────────────────────────────────
DRY_RUN=false
SINGLE_DB=""

usage() {
    cat <<EOF
Usage: $0 [--dry-run] [--db <name>] [-h|--help]

  --dry-run     Run preflight + schema-only dumps; log "would scp" rather than
                actually transferring; skip retention prune.
  --db <name>   Back up only one database (overrides the default 3).
  -h, --help    Show this help.

Default DBs: ${DBS[*]}
EOF
}

while (( $# )); do
    case "$1" in
        --dry-run) DRY_RUN=true; shift ;;
        --db)
            if [[ -z "${2:-}" ]]; then echo "--db requires a name" >&2; exit 1; fi
            SINGLE_DB="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown arg: $1" >&2; usage >&2; exit 1 ;;
    esac
done

if [[ -n "$SINGLE_DB" ]]; then
    DBS=("$SINGLE_DB")
fi

# ─── Init log/manifest dirs ────────────────────────────────────────────
mkdir -p "$LOG_DIR" "$MANIFEST_DIR"
chmod 700 "$LOG_DIR" "$MANIFEST_DIR" 2>/dev/null || true

RUN_TS=$(date -u +%Y-%m-%d_%H%M%S)
RUN_START_S=$(date +%s)
HOST_SHORT=$(hostname -s)

# Running totals (accumulated across DBs; used in run_complete notification)
TOTAL_BYTES=0

# ─── Structured logging ────────────────────────────────────────────────
log_json() {
    local json="$1"
    printf '%s\n' "$json" >> "$LOG_FILE"
    printf '%s\n' "$json" >&2
}

# Build a JSON event from key=value args using jq. Numeric values detected.
make_event() {
    local event="$1"; shift
    local out
    out=$("$JQ" -nc \
        --arg event "$event" \
        --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        --arg run_id "$RUN_TS" \
        --arg host "$HOST_SHORT" \
        '{event: $event, ts: $ts, run_id: $run_id, host: $host}')
    while (( $# )); do
        local kv="$1"; shift
        local k="${kv%%=*}"
        local v="${kv#*=}"
        if [[ "$v" =~ ^-?[0-9]+(\.[0-9]+)?$ ]]; then
            out=$("$JQ" -nc --argjson base "$out" --arg k "$k" --argjson v "$v" \
                  '$base + {($k): $v}')
        else
            out=$("$JQ" -nc --argjson base "$out" --arg k "$k" --arg v "$v" \
                  '$base + {($k): $v}')
        fi
    done
    printf '%s' "$out"
}

# ─── Observability: Mattermost + Buddy events ──────────────────────────
# Both helpers are fire-and-forget. They MUST NOT propagate failures upward.
# Token sourced from ~/jarvis/.secrets (GATEWAY_TOKEN). URL falls back to
# V2 §16 canonical (jarvis-gateway.tail40ed36.ts.net:8283); ALPHA_GATEWAY_URL
# or GATEWAY_URL env may override.

# Usage: mm_notify <severity> <title> <message>
#   severity ∈ {info, needs_input, warning, error, critical}
mm_notify() {
    local severity="$1"; local title="$2"; local message="$3"
    local gateway_url="${ALPHA_GATEWAY_URL:-${GATEWAY_URL:-https://jarvis-gateway.tail40ed36.ts.net:8283}}"

    if [[ -z "${GATEWAY_TOKEN:-}" ]]; then
        log_json "$(make_event mm_notify_skipped reason=no_gateway_token)"
        return 0
    fi

    local payload
    if ! payload=$("$JQ" -nc \
            --arg title "$title" \
            --arg message "$message" \
            --arg severity "$severity" \
            --arg source "alpha" \
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
        -H "X-JARVIS-Idempotency-Key: pg-backup-${RUN_TS}" \
        -d "$payload" 2>/dev/null || echo "000")
    rm -f "$resp_tmp"

    if [[ "$http_code" =~ ^2 ]]; then
        log_json "$(make_event mm_notify_sent severity="$severity" http_code="$http_code")"
    else
        log_json "$(make_event mm_notify_failed severity="$severity" http_code="$http_code")"
    fi
    return 0
}

# Usage: buddy_event <event_type> <title> <body> <priority>
#   event_type ∈ {alert, reminder, suggestion, system}
#   priority ∈ {1=info, 2=warning, 3=critical}
# Postgres dollar-quoting ($$...$$) handles arbitrary title/body text without
# escape leakage — assumes title/body never contain the literal "$$".
buddy_event() {
    local event_type="$1"; local title="$2"; local body="$3"; local priority="$4"

    local payload
    payload=$("$JQ" -nc \
        --arg run_id "$RUN_TS" \
        --arg host "$HOST_SHORT" \
        '{run_id:$run_id, host:$host, source:"pg_backup_alpha"}')

    "$PSQL" -d jarvis_alpha -v ON_ERROR_STOP=0 -c "
        INSERT INTO alpha_buddy_events (event_type, title, body, priority, source, payload)
        VALUES ('$event_type', \$\$$title\$\$, \$\$$body\$\$, $priority, 'pg_backup_alpha', '$payload'::jsonb)
    " > /dev/null 2>&1 \
        || log_json "$(make_event buddy_event_failed event_type="$event_type")"
    return 0
}

# ─── Lock (mkdir-atomic, replaces flock) ───────────────────────────────
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    log_json "$(make_event lock_held action=exit_clean lock_dir="$LOCK_DIR")"
    exit 0
fi
# Always release lock on exit, including failures
trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT

# ─── Preflight ─────────────────────────────────────────────────────────
# Pre-read GATEWAY_TOKEN only (not full source) so mm_notify can fire even if
# preflight fails. Other secrets are sourced after preflight passes.
GATEWAY_TOKEN=$(awk -F= '/^GATEWAY_TOKEN=/{sub(/^[^=]+=/, ""); print; exit}' "$SECRETS_FILE" 2>/dev/null || true)

PREFLIGHT_ERR="$LOG_DIR/pg_backup.preflight.err"
if ! bash "$PREFLIGHT" >/dev/null 2>"$PREFLIGHT_ERR"; then
    log_json "$(make_event preflight_failed errfile="$PREFLIGHT_ERR")"
    mm_notify critical "Backup PREFLIGHT failed" "Backup blocked: preflight checks failed on ${HOST_SHORT}. Inspect: ssh jarvisbrain@jarvis-brain 'bash ~/jarvis-alpha/scripts/preflight_brain_backup.sh' and tail $PREFLIGHT_ERR"
    buddy_event alert "Backup preflight failed" "RUN_TS=${RUN_TS} host=${HOST_SHORT}" 3
    exit 1
fi

# ─── Source secrets ────────────────────────────────────────────────────
set -a
# shellcheck disable=SC1090
source "$SECRETS_FILE"
set +a

for v in BACKUP_SSH_HOST BACKUP_SSH_USER BACKUP_SSH_KEY BACKUP_SSH_TARGET_DIR BACKUP_GPG_PASSPHRASE; do
    if [[ -z "${!v:-}" ]]; then
        log_json "$(make_event secret_missing var="$v")"
        exit 1
    fi
done

PG_DUMP_VERSION=$("$PG_DUMP" --version | head -1)
GIT_COMMIT=$(cd "$SCRIPT_DIR/.." && git rev-parse HEAD 2>/dev/null || echo unknown)

log_json "$(make_event run_start dbs="${DBS[*]}" dry_run="$DRY_RUN" \
            pg_dump_version="$PG_DUMP_VERSION" git_commit="$GIT_COMMIT")"

# ─── Per-DB backup ─────────────────────────────────────────────────────
declare -a MANIFEST_ENTRIES=()

backup_db() {
    local db="$1"
    local out_name="${db}_${RUN_TS}.dump.gpg"
    local local_tmp="$TMP_DIR/$out_name"
    local remote_target="$BACKUP_SSH_TARGET_DIR/dumps/$out_name"
    local remote_partial="${remote_target}.partial"

    # Notify helper that closes over $db. Bash dynamic scope sees outer locals.
    notify_failure() {
        local stage="$1"; local rc="$2"
        mm_notify critical "Backup FAILED (${db})" "DB: ${db}, stage: ${stage}, exit code: ${rc}. See ~/jarvis/logs/pg_backup.log on Brain."
        buddy_event alert "Backup failed: ${db}" "Stage=${stage} rc=${rc} run=${RUN_TS}" 3
    }

    local dump_start; dump_start=$(date +%s)

    # Build pg_dump argv as a non-empty array (avoids bash 3.2 set -u
    # "unbound" complaint on empty array expansion).
    local pg_argv=(--format=custom)
    [[ "$DRY_RUN" == "true" ]] && pg_argv+=(--schema-only)
    pg_argv+=("$db")

    # pg_dump | gpg — capture both exit codes via PIPESTATUS.
    # Snapshot PIPESTATUS into a local array in a SINGLE step right after the
    # pipe; subsequent `local` builtins would otherwise clobber PIPESTATUS
    # before we could read [1].
    set +e
    "$PG_DUMP" "${pg_argv[@]}" \
        | "$GPG" --symmetric --cipher-algo AES256 \
                 --batch --no-tty --quiet \
                 --passphrase-fd 3 \
                 --output "$local_tmp" \
                 3< <(printf '%s' "$BACKUP_GPG_PASSPHRASE")
    local ps_snapshot=("${PIPESTATUS[@]}")
    set -e
    local pg_rc=${ps_snapshot[0]:-1}
    local gpg_rc=${ps_snapshot[1]:-1}

    if (( pg_rc != 0 )); then
        log_json "$(make_event dump_failed db="$db" pg_dump_rc="$pg_rc")"
        notify_failure pg_dump "$pg_rc"
        rm -f "$local_tmp"
        exit 2
    fi
    if (( gpg_rc != 0 )); then
        log_json "$(make_event gpg_failed db="$db" gpg_rc="$gpg_rc")"
        notify_failure gpg "$gpg_rc"
        rm -f "$local_tmp"
        exit 3
    fi

    local bytes; bytes=$(stat -f %z "$local_tmp" 2>/dev/null || stat -c %s "$local_tmp")
    local sha; sha=$("$SHASUM" -a 256 "$local_tmp" | awk '{print $1}')
    chmod 600 "$local_tmp"
    local dump_end; dump_end=$(date +%s)

    log_json "$(make_event dump_complete db="$db" bytes="$bytes" sha256="$sha" \
                duration_ms=$(( (dump_end - dump_start) * 1000 )))"

    if [[ "$DRY_RUN" == "true" ]]; then
        log_json "$(make_event dry_run_skip_transfer db="$db" \
                    would_scp_to="$remote_target")"
        rm -f "$local_tmp"
    else
        local xfer_start; xfer_start=$(date +%s)

        if ! scp -i "$BACKUP_SSH_KEY" -o BatchMode=yes -q \
                "$local_tmp" \
                "${BACKUP_SSH_USER}@${BACKUP_SSH_HOST}:${remote_partial}" \
                2>"$LOG_DIR/pg_backup.scp.err"; then
            log_json "$(make_event scp_failed db="$db" \
                        errfile="$LOG_DIR/pg_backup.scp.err")"
            notify_failure scp "$?"
            rm -f "$local_tmp"
            exit 4
        fi

        local remote_sha
        if ! remote_sha=$(ssh -i "$BACKUP_SSH_KEY" -o BatchMode=yes \
                              "${BACKUP_SSH_USER}@${BACKUP_SSH_HOST}" \
                              "chmod 600 '$remote_partial' && sha256sum '$remote_partial' | awk '{print \$1}'" \
                              2>"$LOG_DIR/pg_backup.ssh.err"); then
            log_json "$(make_event remote_verify_failed db="$db" \
                        errfile="$LOG_DIR/pg_backup.ssh.err")"
            notify_failure remote_sha "$?"
            rm -f "$local_tmp"
            exit 5
        fi

        if [[ "$remote_sha" != "$sha" ]]; then
            log_json "$(make_event sha_mismatch db="$db" \
                        local_sha="$sha" remote_sha="$remote_sha")"
            notify_failure sha_mismatch "$sha vs $remote_sha"
            rm -f "$local_tmp"
            exit 5
        fi

        if ! ssh -i "$BACKUP_SSH_KEY" -o BatchMode=yes \
                 "${BACKUP_SSH_USER}@${BACKUP_SSH_HOST}" \
                 "mv '$remote_partial' '$remote_target'" \
                 2>"$LOG_DIR/pg_backup.ssh.err"; then
            log_json "$(make_event atomic_rename_failed db="$db" \
                        errfile="$LOG_DIR/pg_backup.ssh.err")"
            notify_failure atomic_rename "$?"
            rm -f "$local_tmp"
            exit 4
        fi

        rm -f "$local_tmp"
        local xfer_end; xfer_end=$(date +%s)
        log_json "$(make_event transfer_complete db="$db" bytes="$bytes" \
                    sha256="$sha" duration_ms=$(( (xfer_end - xfer_start) * 1000 )) \
                    remote_path="$remote_target")"
    fi

    MANIFEST_ENTRIES+=("$("$JQ" -nc \
        --arg db "$db" \
        --arg file "$out_name" \
        --argjson bytes "$bytes" \
        --arg sha256 "$sha" \
        '{db: $db, file: $file, bytes: $bytes, sha256: $sha256}')")

    # Accumulate for run_complete summary (global; bash dynamic scope persists)
    TOTAL_BYTES=$(( TOTAL_BYTES + bytes ))
}

for db in "${DBS[@]}"; do
    backup_db "$db"
done

# Defense-in-depth: drop passphrase from env as soon as no longer needed
unset BACKUP_GPG_PASSPHRASE

# ─── Manifest ──────────────────────────────────────────────────────────
MANIFEST_LOCAL="$MANIFEST_DIR/$RUN_TS.json"
MANIFEST_REMOTE="$BACKUP_SSH_TARGET_DIR/manifests/$RUN_TS.json"

DBS_JSON=$(printf '%s\n' "${MANIFEST_ENTRIES[@]}" | "$JQ" -sc '.')

if ! "$JQ" -nc \
        --arg run_id "$RUN_TS" \
        --arg run_ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        --arg host "$HOST_SHORT" \
        --arg git_commit "$GIT_COMMIT" \
        --arg pg_dump_version "$PG_DUMP_VERSION" \
        --arg dry_run "$DRY_RUN" \
        --argjson dbs "$DBS_JSON" \
        '{run_id: $run_id, run_ts: $run_ts, host: $host,
          git_commit: $git_commit, pg_dump_version: $pg_dump_version,
          dry_run: ($dry_run == "true"), dbs: $dbs}' \
        > "$MANIFEST_LOCAL"; then
    log_json "$(make_event manifest_build_failed)"
    exit 6
fi
chmod 600 "$MANIFEST_LOCAL"

if [[ "$DRY_RUN" != "true" ]]; then
    if ! scp -i "$BACKUP_SSH_KEY" -o BatchMode=yes -q \
            "$MANIFEST_LOCAL" \
            "${BACKUP_SSH_USER}@${BACKUP_SSH_HOST}:${MANIFEST_REMOTE}" \
            2>"$LOG_DIR/pg_backup.scp.err"; then
        log_json "$(make_event manifest_scp_failed errfile="$LOG_DIR/pg_backup.scp.err")"
        exit 6
    fi
    ssh -i "$BACKUP_SSH_KEY" -o BatchMode=yes \
        "${BACKUP_SSH_USER}@${BACKUP_SSH_HOST}" \
        "chmod 600 '$MANIFEST_REMOTE'" >/dev/null 2>&1 || true
fi

log_json "$(make_event manifest_written local="$MANIFEST_LOCAL" remote="$MANIFEST_REMOTE")"

# ─── Retention prune ───────────────────────────────────────────────────
prune_retention() {
    local list
    if ! list=$(ssh -i "$BACKUP_SSH_KEY" -o BatchMode=yes \
                    "${BACKUP_SSH_USER}@${BACKUP_SSH_HOST}" \
                    "ls -1 '$BACKUP_SSH_TARGET_DIR/dumps/' 2>/dev/null | grep '\\.dump\\.gpg$' || true" \
                    2>"$LOG_DIR/pg_backup.prune.err"); then
        log_json "$(make_event retention_list_failed errfile="$LOG_DIR/pg_backup.prune.err")"
        return 7
    fi

    local today_epoch; today_epoch=$(date -u +%s)
    local cutoff=$(( today_epoch - 30*86400 ))
    local kept=0
    local to_delete=()

    while IFS= read -r bn; do
        [[ -z "$bn" ]] && continue
        if [[ "$bn" =~ _([0-9]{4})-([0-9]{2})-([0-9]{2})_ ]]; then
            local y="${BASH_REMATCH[1]}"
            local m="${BASH_REMATCH[2]}"
            local d="${BASH_REMATCH[3]}"
            local fe
            # macOS first, then GNU date
            fe=$(date -j -f "%Y-%m-%d" "$y-$m-$d" +%s 2>/dev/null) \
                || fe=$(date -d "$y-$m-$d" +%s 2>/dev/null) \
                || fe=0
            if (( fe >= cutoff )); then
                kept=$(( kept + 1 ))
            elif [[ "$d" == "01" ]]; then
                kept=$(( kept + 1 ))
            else
                to_delete+=("$bn")
            fi
        fi
    done <<< "$list"

    if (( ${#to_delete[@]} > 0 )); then
        local rm_cmd=""
        for f in "${to_delete[@]}"; do
            rm_cmd+="rm -f '$BACKUP_SSH_TARGET_DIR/dumps/$f' ; "
        done
        rm_cmd+="echo PRUNE_DONE"
        if ! ssh -i "$BACKUP_SSH_KEY" -o BatchMode=yes \
                 "${BACKUP_SSH_USER}@${BACKUP_SSH_HOST}" \
                 "$rm_cmd" >/dev/null 2>"$LOG_DIR/pg_backup.prune.err"; then
            log_json "$(make_event retention_delete_failed deleted_count="${#to_delete[@]}" \
                        errfile="$LOG_DIR/pg_backup.prune.err")"
            return 7
        fi
        for f in "${to_delete[@]}"; do
            log_json "$(make_event retention_deleted file="$f")"
        done
    fi

    log_json "$(make_event retention_complete kept="$kept" deleted="${#to_delete[@]}")"
    return 0
}

if [[ "$DRY_RUN" != "true" ]]; then
    if ! prune_retention; then
        log_json "$(make_event retention_skipped_due_to_error note=non-fatal)"
    fi
else
    log_json "$(make_event retention_skipped reason=dry_run)"
fi

# ─── Done ──────────────────────────────────────────────────────────────
RUN_END_S=$(date +%s)
DURATION_S=$(( RUN_END_S - RUN_START_S ))
TOTAL_MB=$(echo "scale=2; ${TOTAL_BYTES} / 1048576" | bc 2>/dev/null || echo "?")

log_json "$(make_event run_complete status=ok \
            duration_ms=$(( DURATION_S * 1000 )) \
            dbs_count="${#DBS[@]}" total_bytes="$TOTAL_BYTES" \
            dry_run="$DRY_RUN")"

if [[ "$DRY_RUN" == "true" ]]; then
    mm_notify info "Backup DRY-RUN OK · ${#DBS[@]} DBs · ${TOTAL_MB} MB" "Run ${RUN_TS} · Duration ${DURATION_S}s · dry-run (schema-only, no remote writes) · Manifest: ${MANIFEST_LOCAL}"
    buddy_event system "Backup dry-run complete" "DBs=${#DBS[@]} size=${TOTAL_MB}MB duration=${DURATION_S}s run=${RUN_TS}" 1
else
    mm_notify info "Backup OK · ${#DBS[@]} DBs · ${TOTAL_MB} MB" "Run ${RUN_TS} · Duration ${DURATION_S}s · Manifest: ${MANIFEST_REMOTE}"
    buddy_event system "Backup complete" "DBs=${#DBS[@]} size=${TOTAL_MB}MB duration=${DURATION_S}s run=${RUN_TS}" 1
fi
exit 0
