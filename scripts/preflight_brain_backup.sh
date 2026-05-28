#!/bin/bash
# preflight_brain_backup.sh — Brain → Unraid SSH backup preflight (STOP GATE 0.5)
#
# Pivoted from SMB to SSH 2026-05-27 (see Session 1 handoff).
# Original SMB version was scripts/preflight_brain_backup_mount.sh (deleted before
# first commit — never landed in git, so no history to point at). Pivot driver:
# INF-001 (broken SMB transport, undetected for ~2 months) and defense-in-depth
# preference for SSH/SCP with symmetric GPG encrypt-before-push.
#
# Run on Brain ONLY. Never echoes secret values.
# Output: JSON on stdout. Human-readable status on stderr.
#
# Usage: bash ~/jarvis-alpha/scripts/preflight_brain_backup.sh

set -uo pipefail
# NOTE: do NOT enable `set -x` — would risk exposing secrets file path/contents.

SECRETS_FILE="$HOME/jarvis/.secrets"
PG_DUMP="/opt/homebrew/Cellar/postgresql@16/16.13/bin/pg_dump"
REQUIRED_FREE_GB=50

log() { printf '[preflight] %s\n' "$*" >&2; }
ok()  { printf '[preflight]   ✓ %s\n' "$*" >&2; }
bad() { printf '[preflight]   ✗ %s\n' "$*" >&2; }

# Results (defaults)
HOST_OK=false
KEY_PERM_OK=false
SSH_OK=false
TARGET_WRITABLE=false
FREE_GB_REMOTE=0
PASSPHRASE_SET=false
PG_DUMP_OK=false
FAIL_REASONS=()

# Read a single VAR=value line from secrets without sourcing. Never echo the value.
read_secret() {
    local key="$1"
    awk -F= -v k="$key" '$1==k {sub(/^[^=]+=/, ""); print; exit}' "$SECRETS_FILE" 2>/dev/null
}

emit_json() {
    local fail_json="[]"
    if (( ${#FAIL_REASONS[@]} > 0 )); then
        fail_json="[$(printf '"%s",' "${FAIL_REASONS[@]}" | sed 's/,$//')]"
    fi
    cat <<JSON
{"host_ok":${HOST_OK},"key_perm_ok":${KEY_PERM_OK},"ssh_ok":${SSH_OK},"target_writable":${TARGET_WRITABLE},"free_gb_remote":${FREE_GB_REMOTE},"passphrase_set":${PASSPHRASE_SET},"pg_dump_ok":${PG_DUMP_OK},"fail_reasons":${fail_json}}
JSON
}

# ──────────────────────────────────────────────────────────────────────────
# 1. Assert running on Brain
# ──────────────────────────────────────────────────────────────────────────
log "=== STOP GATE 0.5 · Brain → Unraid SSH backup preflight ==="
SHORT_HOST=$(hostname -s 2>/dev/null || hostname)
log "Host: $SHORT_HOST  User: ${USER:-unknown}"
if [[ "${USER:-}" == "jarvisbrain" ]] || [[ "$SHORT_HOST" == jarvis-brain* ]]; then
    HOST_OK=true
    ok "Brain identity confirmed (user=$USER, host=$SHORT_HOST)"
else
    bad "Not Brain — refusing to run (user=$USER, host=$SHORT_HOST)"
    FAIL_REASONS+=("not_on_brain")
    emit_json
    exit 1
fi

# ──────────────────────────────────────────────────────────────────────────
# 2. Secrets file exists + required keys present
# ──────────────────────────────────────────────────────────────────────────
if [[ ! -f "$SECRETS_FILE" ]]; then
    bad "Secrets file not found at $SECRETS_FILE"
    FAIL_REASONS+=("secrets_file_missing")
    emit_json
    exit 1
fi

BACKUP_SSH_HOST=$(read_secret BACKUP_SSH_HOST)
BACKUP_SSH_USER=$(read_secret BACKUP_SSH_USER)
BACKUP_SSH_KEY=$(read_secret BACKUP_SSH_KEY)
BACKUP_SSH_TARGET_DIR=$(read_secret BACKUP_SSH_TARGET_DIR)

for var_name in BACKUP_SSH_HOST BACKUP_SSH_USER BACKUP_SSH_KEY BACKUP_SSH_TARGET_DIR; do
    if [[ -z "${!var_name}" ]]; then
        bad "$var_name not set in $SECRETS_FILE"
        FAIL_REASONS+=("${var_name,,}_missing")
    fi
done

if (( ${#FAIL_REASONS[@]} > 0 )); then
    emit_json
    exit 1
fi
ok "BACKUP_SSH_HOST / USER / KEY / TARGET_DIR all set (values not displayed)"

# ──────────────────────────────────────────────────────────────────────────
# 3. SSH key file: exists, mode 600, readable
# ──────────────────────────────────────────────────────────────────────────
if [[ -f "$BACKUP_SSH_KEY" ]]; then
    KEY_MODE=$(stat -f '%Lp' "$BACKUP_SSH_KEY" 2>/dev/null || stat -c '%a' "$BACKUP_SSH_KEY" 2>/dev/null)
    if [[ "$KEY_MODE" == "600" ]]; then
        KEY_PERM_OK=true
        ok "SSH key exists with mode 600"
    else
        bad "SSH key mode is $KEY_MODE (expected 600)"
        FAIL_REASONS+=("key_mode_unsafe")
    fi
else
    bad "SSH key not found at $BACKUP_SSH_KEY"
    FAIL_REASONS+=("key_missing")
fi

# ──────────────────────────────────────────────────────────────────────────
# 4. Passwordless SSH to Unraid (BatchMode — no password prompt allowed)
# ──────────────────────────────────────────────────────────────────────────
if [[ "$KEY_PERM_OK" == "true" ]]; then
    if SSH_OUTPUT=$(ssh -i "$BACKUP_SSH_KEY" \
                       -o BatchMode=yes \
                       -o StrictHostKeyChecking=accept-new \
                       -o ConnectTimeout=10 \
                       "$BACKUP_SSH_USER@$BACKUP_SSH_HOST" \
                       'echo OK-$(hostname)' 2>&1); then
        if [[ "$SSH_OUTPUT" =~ ^OK- ]]; then
            SSH_OK=true
            ok "SSH login passwordless: $SSH_OUTPUT"
        else
            bad "SSH connected but unexpected output: $SSH_OUTPUT"
            FAIL_REASONS+=("ssh_unexpected_output")
        fi
    else
        bad "SSH failed: $SSH_OUTPUT"
        FAIL_REASONS+=("ssh_failed")
    fi
fi

# ──────────────────────────────────────────────────────────────────────────
# 5. Remote target dir exists + writable (touch + rm)
# ──────────────────────────────────────────────────────────────────────────
if [[ "$SSH_OK" == "true" ]]; then
    HEALTHCHECK=".preflight-healthcheck-$(date +%s)-$$"
    REMOTE_CMD="cd '$BACKUP_SSH_TARGET_DIR' 2>/dev/null && touch '$HEALTHCHECK' && rm '$HEALTHCHECK' && echo WRITE_OK || echo WRITE_FAIL"
    if WRITE_RESULT=$(ssh -i "$BACKUP_SSH_KEY" -o BatchMode=yes \
                          "$BACKUP_SSH_USER@$BACKUP_SSH_HOST" \
                          "$REMOTE_CMD" 2>&1); then
        if [[ "$WRITE_RESULT" == *"WRITE_OK"* ]]; then
            TARGET_WRITABLE=true
            ok "Remote target writable: $BACKUP_SSH_TARGET_DIR"
        else
            bad "Remote target write test failed: $WRITE_RESULT"
            FAIL_REASONS+=("target_not_writable")
        fi
    else
        bad "Remote write test SSH call failed: $WRITE_RESULT"
        FAIL_REASONS+=("target_check_failed")
    fi
fi

# ──────────────────────────────────────────────────────────────────────────
# 6. Remote free space ≥ 50 GB (parse df from remote)
# ──────────────────────────────────────────────────────────────────────────
if [[ "$SSH_OK" == "true" ]]; then
    # df -P → POSIX (1K blocks), column 4 = available
    DF_LINE=$(ssh -i "$BACKUP_SSH_KEY" -o BatchMode=yes \
                  "$BACKUP_SSH_USER@$BACKUP_SSH_HOST" \
                  "df -P '$BACKUP_SSH_TARGET_DIR'" 2>/dev/null | awk 'NR==2 {print $4}')
    if [[ -n "$DF_LINE" ]] && [[ "$DF_LINE" =~ ^[0-9]+$ ]]; then
        FREE_GB_REMOTE=$(( DF_LINE / 1024 / 1024 ))
        if (( FREE_GB_REMOTE >= REQUIRED_FREE_GB )); then
            ok "Remote free space: ${FREE_GB_REMOTE} GB (≥ ${REQUIRED_FREE_GB} GB)"
        else
            bad "Remote free space ${FREE_GB_REMOTE} GB — below ${REQUIRED_FREE_GB} GB threshold"
            FAIL_REASONS+=("insufficient_space")
        fi
    else
        bad "Could not read remote df output"
        FAIL_REASONS+=("df_failed")
    fi
fi

# ──────────────────────────────────────────────────────────────────────────
# 7. BACKUP_GPG_PASSPHRASE existence (never echo value)
# ──────────────────────────────────────────────────────────────────────────
if grep -qE '^BACKUP_GPG_PASSPHRASE=.+' "$SECRETS_FILE"; then
    PASSPHRASE_SET=true
    ok "BACKUP_GPG_PASSPHRASE present (value not displayed)"
else
    bad "BACKUP_GPG_PASSPHRASE not found (or empty) in $SECRETS_FILE"
    FAIL_REASONS+=("passphrase_missing")
fi

# ──────────────────────────────────────────────────────────────────────────
# 8. pg_dump binary works
# ──────────────────────────────────────────────────────────────────────────
if [[ -x "$PG_DUMP" ]]; then
    PG_VERSION=$("$PG_DUMP" --version 2>/dev/null || true)
    if [[ -n "$PG_VERSION" ]]; then
        PG_DUMP_OK=true
        ok "pg_dump OK: $PG_VERSION"
    else
        bad "pg_dump at $PG_DUMP exists but --version failed"
        FAIL_REASONS+=("pg_dump_broken")
    fi
else
    bad "pg_dump not executable at $PG_DUMP"
    FAIL_REASONS+=("pg_dump_missing")
fi

# ──────────────────────────────────────────────────────────────────────────
# Final output
# ──────────────────────────────────────────────────────────────────────────
emit_json

if (( ${#FAIL_REASONS[@]} > 0 )); then
    log "FAIL — ${#FAIL_REASONS[@]} check(s) failed: ${FAIL_REASONS[*]}"
    exit 1
fi
log "PASS — all checks green"
exit 0
