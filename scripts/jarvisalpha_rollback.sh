#!/usr/bin/env bash
# scripts/jarvisalpha_rollback.sh
# Revert a previously-merged PR via the GitHub PR path.
# Closes AUDIT-7. Policy: docs/adr/ADR-0014-rollback-policy.md
# Symmetric to scripts/jarvisalpha_deploy.sh for forward changes.

set -euo pipefail

# ============================================================
# Constants
# ============================================================

SCRIPT_NAME="jarvisalpha_rollback.sh"
REPO="kphaas/jarvis-alpha"
BACKUP_MAX_AGE_HOURS=36
SECRETS_FILE="$HOME/.secrets"

# ============================================================
# State (populated by parse_args + resolve_pr)
# ============================================================

TARGET_PR=""
MODE="dry-run"
SKIP_CONFIRM=0
DB_RESTORED=0
SKIP_BACKUP_CHECK=0

PR_STATE=""
PR_MERGE_SHA=""
PR_TITLE=""
PR_AUTHOR=""
PR_MERGED_AT=""
PR_FILES_CHANGED=0
DB_MIGRATION_PRESENT=0
DB_MIGRATION_FILES=""
BACKUP_AGE_HOURS=""

# ============================================================
# Eventing helpers (graceful fallback if external helpers unavailable)
# ============================================================

emit_event() {
    local event_name="$1"
    local detail_json="${2:-{}}"
    printf '##EVT##{"event":"%s","script":"%s","ts":"%s","detail":%s}\n' \
        "$event_name" "$SCRIPT_NAME" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$detail_json" >&2
}

mm_notify() {
    local channel="$1"
    local message="$2"
    if command -v mm_notify_helper >/dev/null 2>&1; then
        mm_notify_helper "$channel" "$message" || true
    fi
}

buddy_event() {
    local severity="$1"
    local message="$2"
    if command -v buddy_event_helper >/dev/null 2>&1; then
        buddy_event_helper "$severity" "$message" || true
    fi
}

# ============================================================
# Help
# ============================================================

show_help() {
    cat <<'HELP'
USAGE:
    scripts/jarvisalpha_rollback.sh <PR_NUMBER> [flags]

DESCRIPTION:
    Revert a previously-merged PR via the GitHub PR path. Symmetric to
    scripts/jarvisalpha_deploy.sh. PR-revert is the ONLY rollback path
    (force-push is blocked; branch protection enforces PR).
    See docs/adr/ADR-0014-rollback-policy.md.

MODES (mutually exclusive):
    --dry-run     Default. Print plan, exit. Always run this first.
    --open        Create revert PR, exit. Operator merges + redeploys manually.
    --full        Create revert PR -> watch CI -> self-merge -> run deploy.
                  Requires explicit --yes.

SAFETY FLAGS:
    --yes                 Skip interactive confirmation (required for --full)
    --db-restored         Override DB-migration halt (operator asserts backup restored)
    --skip-backup-check   Override backup-recency halt (NOT recommended)
    --help, -h            Show this help

EXIT CODES:
    0  Success or successful dry-run
    1  User error (bad args, declined confirm, preflight failed)
    2  Revert PR CI failed in --full mode
    3  Backup recency check failed
    4  DB migration detected without --db-restored
    5  Post-merge deploy failed in --full mode

EXAMPLES:
    scripts/jarvisalpha_rollback.sh 156 --dry-run
    scripts/jarvisalpha_rollback.sh 156 --open
    scripts/jarvisalpha_rollback.sh 156 --full --yes
HELP
}

# ============================================================
# Arg parsing
# ============================================================

parse_args() {
    if [[ $# -eq 0 ]]; then
        show_help
        exit 1
    fi

    case "${1:-}" in
        --help|-h)
            show_help
            exit 0
            ;;
    esac

    TARGET_PR="$1"
    shift

    if ! [[ "$TARGET_PR" =~ ^[0-9]+$ ]]; then
        printf "ERROR: First argument must be a PR number. Got: '%s'\n" "$TARGET_PR" >&2
        printf "Run with --help for usage.\n" >&2
        exit 1
    fi

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --dry-run)            MODE="dry-run" ;;
            --open)               MODE="open" ;;
            --full)               MODE="full" ;;
            --yes)                SKIP_CONFIRM=1 ;;
            --db-restored)        DB_RESTORED=1 ;;
            --skip-backup-check)  SKIP_BACKUP_CHECK=1 ;;
            --help|-h)            show_help; exit 0 ;;
            *)
                printf "ERROR: Unknown flag: %s\n" "$1" >&2
                printf "Run with --help for usage.\n" >&2
                exit 1
                ;;
        esac
        shift
    done

    if [[ "$MODE" == "full" ]] && [[ "$SKIP_CONFIRM" -ne 1 ]]; then
        printf "ERROR: --full mode requires explicit --yes flag.\n" >&2
        printf "This is a safety guard against accidental full rollbacks.\n" >&2
        exit 1
    fi
}

# ============================================================
# Failure box (mirrors deploy script pattern)
# ============================================================

failure_box() {
    local exit_code="$1"
    local stage="$2"
    cat >&2 <<EOF

╔══════════════════════════════════════════════════════════════════════╗
║  ROLLBACK FAILED                                                     ║
╠══════════════════════════════════════════════════════════════════════╣
║  Stage:  $stage
║  Exit:   $exit_code
║  PR:     #$TARGET_PR
║  Mode:   $MODE
╠══════════════════════════════════════════════════════════════════════╣
║  RECOVERY:                                                           ║
║    1. Inspect any revert PR that may have been opened:               ║
║       gh pr list --repo $REPO --search "Revert" --limit 5
║    2. If --full failed mid-flow, the revert PR may need manual       ║
║       completion: gh pr merge <N> --repo $REPO --squash --delete-branch
║    3. Restart deploy: bash scripts/jarvisalpha_deploy.sh "<msg>"     ║
║    4. To rollback the rollback: rerun this script on the revert PR   ║
╚══════════════════════════════════════════════════════════════════════╝
EOF
    emit_event "rollback_failed" "{\"stage\":\"$stage\",\"exit_code\":$exit_code,\"pr\":$TARGET_PR}"
    mm_notify "#alerts" ":rotating_light: Rollback of PR #$TARGET_PR FAILED at stage: $stage (exit $exit_code)"
    buddy_event "high" "Rollback PR#$TARGET_PR failed at $stage"
    exit "$exit_code"
}

# ============================================================
# Preflight
# ============================================================

preflight_checks() {
    emit_event "preflight_start" "{\"pr\":$TARGET_PR}"

    if [[ ! -d ".git" ]] || ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        printf "ERROR: not in a git repo. Run from jarvis-alpha repo root.\n" >&2
        failure_box 1 "preflight:not-in-repo"
    fi

    local current_branch
    current_branch=$(git symbolic-ref --short HEAD 2>/dev/null || echo "")
    if [[ "$current_branch" != "main" ]]; then
        printf "ERROR: must be on main branch. Currently on: %s\n" "$current_branch" >&2
        failure_box 1 "preflight:not-on-main"
    fi

    if ! git diff-index --quiet HEAD --; then
        printf "ERROR: working tree is dirty. Commit or stash before rolling back.\n" >&2
        failure_box 1 "preflight:dirty-tree"
    fi

    git fetch origin main --quiet
    local local_head origin_head
    local_head=$(git rev-parse HEAD)
    origin_head=$(git rev-parse origin/main)
    if [[ "$local_head" != "$origin_head" ]]; then
        printf "ERROR: local main is not in sync with origin/main.\n" >&2
        printf "  Local:  %s\n" "$local_head" >&2
        printf "  Origin: %s\n" "$origin_head" >&2
        printf "Run: git pull --ff-only origin main\n" >&2
        failure_box 1 "preflight:not-ff"
    fi

    if [[ ! -f "$SECRETS_FILE" ]]; then
        printf "ERROR: secrets file not found at %s\n" "$SECRETS_FILE" >&2
        printf "  This script expects Sandbox conventions (~/.secrets).\n" >&2
        printf "  If running on Brain/Gateway/Endpoint, secrets are at ~/jarvis/.secrets.\n" >&2
        failure_box 1 "preflight:secrets-missing"
    fi

    if ! gh auth status >/dev/null 2>&1; then
        printf "ERROR: gh CLI not authenticated. Run: gh auth login\n" >&2
        failure_box 1 "preflight:gh-auth"
    fi

    emit_event "preflight_pass" "{}"
}

# ============================================================
# PR resolution
# ============================================================

resolve_pr() {
    emit_event "resolve_pr_start" "{\"pr\":$TARGET_PR}"

    local pr_json
    if ! pr_json=$(gh pr view "$TARGET_PR" --repo "$REPO" --json number,state,mergedAt,mergeCommit,title,author 2>&1); then
        printf "ERROR: cannot resolve PR #%s in %s\n" "$TARGET_PR" "$REPO" >&2
        printf "%s\n" "$pr_json" >&2
        failure_box 1 "resolve:not-found"
    fi

    PR_STATE=$(echo "$pr_json" | jq -r '.state')
    PR_MERGE_SHA=$(echo "$pr_json" | jq -r '.mergeCommit.oid // empty')
    PR_TITLE=$(echo "$pr_json" | jq -r '.title')
    PR_AUTHOR=$(echo "$pr_json" | jq -r '.author.login // "unknown"')
    PR_MERGED_AT=$(echo "$pr_json" | jq -r '.mergedAt // "(unknown)"')

    if [[ "$PR_STATE" != "MERGED" ]]; then
        printf "ERROR: PR #%s is not MERGED (state: %s).\n" "$TARGET_PR" "$PR_STATE" >&2
        printf "Cannot revert an unmerged PR.\n" >&2
        failure_box 1 "resolve:not-merged"
    fi

    if [[ -z "$PR_MERGE_SHA" ]]; then
        printf "ERROR: PR #%s has no merge commit SHA.\n" "$TARGET_PR" >&2
        failure_box 1 "resolve:no-sha"
    fi

    if ! git cat-file -e "$PR_MERGE_SHA" 2>/dev/null; then
        printf "ERROR: merge commit %s not in local repo. Run: git fetch\n" "$PR_MERGE_SHA" >&2
        failure_box 1 "resolve:sha-not-local"
    fi

    if ! git merge-base --is-ancestor "$PR_MERGE_SHA" HEAD; then
        printf "ERROR: merge commit %s is not an ancestor of current main HEAD.\n" "$PR_MERGE_SHA" >&2
        printf "PR may have already been reverted, or main history is unusual.\n" >&2
        failure_box 1 "resolve:not-ancestor"
    fi

    PR_FILES_CHANGED=$(git diff --name-only "$PR_MERGE_SHA~1" "$PR_MERGE_SHA" | wc -l | tr -d ' ')

    emit_event "resolve_pr_done" "{\"pr\":$TARGET_PR,\"sha\":\"$PR_MERGE_SHA\",\"files\":$PR_FILES_CHANGED}"
}

# ============================================================
# DB migration detection
# ============================================================

detect_db_migration() {
    emit_event "db_migration_check_start" "{}"

    local migration_files
    migration_files=$(git diff --name-only "$PR_MERGE_SHA~1" "$PR_MERGE_SHA" | grep '^brain/db/migrations/' || true)

    if [[ -z "$migration_files" ]]; then
        DB_MIGRATION_PRESENT=0
        emit_event "db_migration_none" "{}"
        return 0
    fi

    DB_MIGRATION_PRESENT=1
    DB_MIGRATION_FILES="$migration_files"

    if [[ "$DB_RESTORED" -ne 1 ]]; then
        cat >&2 <<EOF

╔══════════════════════════════════════════════════════════════════════╗
║  HALT: DB MIGRATION IN REVERT RANGE                                  ║
╠══════════════════════════════════════════════════════════════════════╣
║  PR #$TARGET_PR contains DB migration file(s):
$(echo "$migration_files" | sed 's/^/║    /')
║                                                                      ║
║  Reverting the code WITHOUT reverting the schema leaves the DB ahead ║
║  of code expectations — DATA INTEGRITY RISK.                         ║
║                                                                      ║
║  RECOVERY:                                                           ║
║  1. Identify a backup taken BEFORE this PR was merged:               ║
║       PR merge time: $PR_MERGED_AT
║     Unraid: /mnt/user/Backups/jarvis-alpha/dumps/                    ║
║  2. Manually restore the DB from that backup                         ║
║  3. Re-run this script with --db-restored flag                       ║
║                                                                      ║
║  Policy: docs/adr/ADR-0014-rollback-policy.md                        ║
╚══════════════════════════════════════════════════════════════════════╝
EOF
        emit_event "db_migration_halt" "{}"
        exit 4
    fi

    emit_event "db_migration_override" "{}"
}

# ============================================================
# Backup recency check
# ============================================================

check_backup_recency() {
    if [[ "$SKIP_BACKUP_CHECK" -eq 1 ]]; then
        BACKUP_AGE_HOURS="(skipped)"
        emit_event "backup_check_skipped" "{}"
        return 0
    fi

    emit_event "backup_check_start" "{}"

    # shellcheck disable=SC1090
    source "$SECRETS_FILE"

    # Sandbox runs this script — uses the read-only RESTORE_SSH_* credentials
    # already provisioned for restore_drill_alpha.sh. The push-side BACKUP_SSH_*
    # credentials live on Brain only (~/jarvis/.secrets) and aren't needed here.
    : "${RESTORE_SSH_HOST:?RESTORE_SSH_HOST not set in $SECRETS_FILE}"
    : "${RESTORE_SSH_USER:?RESTORE_SSH_USER not set in $SECRETS_FILE}"
    : "${RESTORE_SSH_KEY:?RESTORE_SSH_KEY not set in $SECRETS_FILE}"
    : "${RESTORE_SSH_SOURCE_DIR:?RESTORE_SSH_SOURCE_DIR not set in $SECRETS_FILE}"

    local latest_mtime now age_seconds age_hours
    if ! latest_mtime=$(ssh -i "$RESTORE_SSH_KEY" \
                            -o BatchMode=yes \
                            -o ConnectTimeout=10 \
                            "$RESTORE_SSH_USER@$RESTORE_SSH_HOST" \
                            "stat -c %Y \$(ls -t $RESTORE_SSH_SOURCE_DIR/jarvis_alpha_*.dump.gpg 2>/dev/null | head -1)" 2>&1); then
        printf "ERROR: cannot query Unraid backups: %s\n" "$latest_mtime" >&2
        failure_box 3 "backup_check:ssh-failed"
    fi

    if [[ -z "$latest_mtime" ]] || ! [[ "$latest_mtime" =~ ^[0-9]+$ ]]; then
        printf "ERROR: no backup found or invalid mtime: '%s'\n" "$latest_mtime" >&2
        failure_box 3 "backup_check:no-backup"
    fi

    now=$(date +%s)
    age_seconds=$((now - latest_mtime))
    age_hours=$((age_seconds / 3600))
    BACKUP_AGE_HOURS="${age_hours}h"

    if [[ "$age_hours" -gt "$BACKUP_MAX_AGE_HOURS" ]]; then
        printf "ERROR: newest backup is %dh old (max allowed: %dh).\n" "$age_hours" "$BACKUP_MAX_AGE_HOURS" >&2
        printf "Backup pipeline may be broken. Investigate before rolling back.\n" >&2
        printf "Override with --skip-backup-check (NOT recommended).\n" >&2
        failure_box 3 "backup_check:stale-backup"
    fi

    emit_event "backup_check_pass" "{\"age_hours\":$age_hours}"
}

# ============================================================
# Dry-run / plan output
# ============================================================

print_plan() {
    local db_mig_label
    if [[ "$DB_MIGRATION_PRESENT" -eq 1 ]]; then
        db_mig_label="YES (override active via --db-restored)"
    else
        db_mig_label="no"
    fi

    cat <<EOF

╔══════════════════════════════════════════════════════════════════════╗
║  ROLLBACK PLAN — PR #$TARGET_PR
╠══════════════════════════════════════════════════════════════════════╣
║  Title:          $PR_TITLE
║  Author:         $PR_AUTHOR
║  Merged at:      $PR_MERGED_AT
║  Merge SHA:      $PR_MERGE_SHA
║  Files changed:  $PR_FILES_CHANGED
║  DB migration:   $db_mig_label
║  Backup age:     $BACKUP_AGE_HOURS (max: ${BACKUP_MAX_AGE_HOURS}h)
║  Mode:           --$MODE
╠══════════════════════════════════════════════════════════════════════╣
║  ACTIONS:                                                            ║
EOF
    case "$MODE" in
        dry-run)
            echo "║    [dry-run] No actions will be taken.                               ║"
            echo "║    Re-run with --open or --full to execute.                          ║"
            ;;
        open)
            echo "║    1. gh pr revert $TARGET_PR --repo $REPO"
            echo "║    2. Print revert PR URL                                            ║"
            echo "║    3. Exit (operator reviews + merges + redeploys manually)          ║"
            ;;
        full)
            echo "║    1. gh pr revert $TARGET_PR --repo $REPO"
            echo "║    2. Watch CI on revert PR (poll every 30s)                         ║"
            echo "║    3. Self-merge on 6 green checks                                   ║"
            echo "║    4. git pull --ff-only origin main                                 ║"
            echo "║    5. bash scripts/jarvisalpha_deploy.sh \"Revert PR #$TARGET_PR\""
            ;;
    esac
    echo "╚══════════════════════════════════════════════════════════════════════╝"
}

# ============================================================
# Interactive confirm
# ============================================================

interactive_confirm() {
    if [[ "$SKIP_CONFIRM" -eq 1 ]] || [[ "$MODE" == "dry-run" ]]; then
        return 0
    fi

    printf "\nProceed with rollback in --%s mode? Type 'yes' to confirm: " "$MODE"
    local answer
    read -r answer
    if [[ "$answer" != "yes" ]]; then
        printf "Aborted by operator.\n"
        emit_event "operator_declined" "{}"
        exit 1
    fi
}

# ============================================================
# Execute: --open mode
# ============================================================

execute_open() {
    emit_event "open_revert_pr_start" "{}"
    mm_notify "#alpha-events" ":rewind: Opening revert PR for #$TARGET_PR ($PR_TITLE)"

    local gh_output revert_pr_url revert_pr_num
    if ! gh_output=$(gh pr revert "$TARGET_PR" --repo "$REPO" 2>&1); then
        printf "ERROR: gh pr revert failed:\n%s\n" "$gh_output" >&2
        failure_box 1 "execute:gh-pr-revert-failed"
    fi

    revert_pr_url=$(echo "$gh_output" | grep -oE 'https://github.com/[^ ]+' | tail -1)
    revert_pr_num=$(echo "$revert_pr_url" | grep -oE '[0-9]+$' || echo "")

    if [[ -z "$revert_pr_num" ]]; then
        printf "WARNING: could not parse revert PR number from gh output:\n%s\n" "$gh_output" >&2
        revert_pr_num="unknown"
    fi

    emit_event "open_revert_pr_done" "{\"revert_pr\":\"$revert_pr_num\",\"url\":\"$revert_pr_url\"}"
    mm_notify "#alpha-events" ":envelope_with_arrow: Revert PR opened: $revert_pr_url"
    buddy_event "high" "Revert PR opened for #$TARGET_PR: $revert_pr_url"

    cat <<EOF

╔══════════════════════════════════════════════════════════════════════╗
║  REVERT PR OPENED                                                    ║
╠══════════════════════════════════════════════════════════════════════╣
║  Original PR: #$TARGET_PR
║  Revert PR:   #$revert_pr_num
║  URL:         $revert_pr_url
║                                                                      ║
║  NEXT STEPS (manual):                                                ║
║  1. Review the revert PR in your browser                             ║
║  2. Wait for CI green (6 required checks)                            ║
║  3. Merge: gh pr merge $revert_pr_num --repo $REPO --squash --delete-branch
║  4. Sync: git checkout main && git pull --ff-only origin main        ║
║  5. Deploy: bash scripts/jarvisalpha_deploy.sh "Revert #$TARGET_PR"
╚══════════════════════════════════════════════════════════════════════╝
EOF
}

# ============================================================
# Execute: --full mode
# ============================================================

execute_full() {
    emit_event "full_revert_start" "{}"
    mm_notify "#alpha-events" ":rewind: --full rollback starting for PR #$TARGET_PR ($PR_TITLE)"

    # Step 1: open revert PR
    local gh_output revert_pr_url revert_pr_num
    if ! gh_output=$(gh pr revert "$TARGET_PR" --repo "$REPO" 2>&1); then
        printf "ERROR: gh pr revert failed:\n%s\n" "$gh_output" >&2
        failure_box 1 "execute:gh-pr-revert-failed"
    fi

    revert_pr_url=$(echo "$gh_output" | grep -oE 'https://github.com/[^ ]+' | tail -1)
    revert_pr_num=$(echo "$revert_pr_url" | grep -oE '[0-9]+$' || echo "")

    if [[ -z "$revert_pr_num" ]]; then
        printf "ERROR: cannot parse revert PR number from gh output:\n%s\n" "$gh_output" >&2
        failure_box 1 "execute:parse-pr-failed"
    fi

    emit_event "full_revert_pr_opened" "{\"revert_pr\":$revert_pr_num,\"url\":\"$revert_pr_url\"}"
    mm_notify "#alpha-events" ":envelope_with_arrow: Revert PR #$revert_pr_num opened. Watching CI..."

    # Step 2: watch CI
    if ! gh pr checks "$revert_pr_num" --repo "$REPO" --watch --interval 30 2>&1; then
        printf "ERROR: revert PR #%s CI failed.\n" "$revert_pr_num" >&2
        printf "Inspect: gh pr checks %s --repo %s\n" "$revert_pr_num" "$REPO" >&2
        printf "Manual recovery via --open mode workflow.\n" >&2
        mm_notify "#alerts" ":rotating_light: Revert PR #$revert_pr_num CI FAILED (rollback of #$TARGET_PR)"
        emit_event "full_ci_failed" "{\"revert_pr\":$revert_pr_num}"
        exit 2
    fi
    emit_event "full_ci_pass" "{\"revert_pr\":$revert_pr_num}"

    # Step 3: merge
    if ! gh pr merge "$revert_pr_num" --repo "$REPO" --squash --delete-branch 2>&1; then
        printf "ERROR: revert PR #%s merge failed.\n" "$revert_pr_num" >&2
        failure_box 1 "execute:merge-failed"
    fi
    emit_event "full_merge_done" "{\"revert_pr\":$revert_pr_num}"
    mm_notify "#alpha-events" ":white_check_mark: Revert PR #$revert_pr_num merged. Running deploy..."

    # Step 4: sync local
    git pull --ff-only origin main --quiet
    local new_head
    new_head=$(git rev-parse --short HEAD)
    emit_event "full_synced" "{\"new_head\":\"$new_head\"}"

    # Step 5: deploy
    if ! bash scripts/jarvisalpha_deploy.sh "Revert PR #$TARGET_PR: $PR_TITLE"; then
        printf "ERROR: post-rollback deploy failed.\n" >&2
        printf "Revert was MERGED to origin/main, but deploy to nodes did not complete.\n" >&2
        printf "Re-run deploy manually after addressing the issue.\n" >&2
        mm_notify "#alerts" ":rotating_light: Rollback merged but DEPLOY FAILED for #$TARGET_PR"
        emit_event "full_deploy_failed" "{}"
        exit 5
    fi

    emit_event "full_done" "{\"revert_pr\":$revert_pr_num,\"new_head\":\"$new_head\"}"
    mm_notify "#alpha-events" ":tada: Rollback of PR #$TARGET_PR complete. New HEAD: $new_head"
    buddy_event "high" "Rollback complete for PR #$TARGET_PR. Revert PR: #$revert_pr_num"

    cat <<EOF

╔══════════════════════════════════════════════════════════════════════╗
║  ROLLBACK COMPLETE                                                   ║
╠══════════════════════════════════════════════════════════════════════╣
║  Reverted PR:    #$TARGET_PR ($PR_TITLE)
║  Revert PR:      #$revert_pr_num (merged + branch deleted)
║  New main HEAD:  $new_head
║  Deploy:         success                                             ║
╚══════════════════════════════════════════════════════════════════════╝
EOF
}

# ============================================================
# Main
# ============================================================

main() {
    parse_args "$@"
    preflight_checks
    resolve_pr
    detect_db_migration
    check_backup_recency
    print_plan

    if [[ "$MODE" == "dry-run" ]]; then
        emit_event "dry_run_complete" "{}"
        exit 0
    fi

    interactive_confirm

    case "$MODE" in
        open) execute_open ;;
        full) execute_full ;;
    esac
}

main "$@"
