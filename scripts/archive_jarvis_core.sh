#!/usr/bin/env bash
# Archive dead jarvis-core paths on Brain under ~/.deprecated/DATE. Uses audit verdicts.
# Runs from Air; operates on Brain via SSH.

set -euo pipefail

BRAIN_SSH="jarvisbrain@jarvis-brain.tail40ed36.ts.net"
JARVIS_ROOT="/Users/jarvisbrain/jarvis"
ARCHIVE_DATE="20260421"
ARCHIVE_ROOT="$JARVIS_ROOT/.deprecated/$ARCHIVE_DATE"
LOG_PATH="$HOME/jarvis-alpha/logs/archive_jarvis_core_$ARCHIVE_DATE.log"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AUDIT_SCRIPT="$SCRIPT_DIR/audit_jarvis_core.sh"

# -- ADDITIONAL items (operator-confirmed safe; still rejected if audit says KEEP)
ADDITIONAL_ITEMS=(
  ".git"
  ".github"
  ".gitignore"
  ".pre-commit-config.yaml"
  ".crontab.bak_20260408_122250"
)

# -- DELETE OUTRIGHT (not archived)
DELETE_ITEMS=(
  ".venv"
  ".pytest_cache"
  ".ruff_cache"
)

MODE=""
EXECUTE_YES=0
EXECUTE_STARTED=0
MOVED_COUNT=0
ERR_COUNT=0
DELETED_COUNT=0
TOTAL_SIZE_BYTES=0
SUMMARY_PRINTED=0

# Doc-only lines for search (not executed):
: <<'ARCHIVE_CLI_DOC'
--plan
--execute
--rollback
SAFE_TO_ARCHIVE
ADDITIONAL items
DELETE OUTRIGHT
ARCHIVE_CLI_DOC

usage() {
  echo "Usage: $0 --plan | --execute [--yes] | --rollback" >&2
  exit 1
}

json_escape_py() {
  export ACTION="$1" SOURCE="$2" DEST="$3" SIZE_BYTES="${4:-0}" STATUS="$5" ERROR_MSG="${6:-}"
  python3 - <<'PY'
import json, os
from datetime import datetime, timezone
rec = {
  "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
  "action": os.environ["ACTION"],
  "source": os.environ["SOURCE"],
  "dest": os.environ["DEST"],
  "size_bytes": int(os.environ["SIZE_BYTES"] or 0),
  "status": os.environ["STATUS"],
  "error_msg": os.environ["ERROR_MSG"],
}
print(json.dumps(rec, ensure_ascii=False))
PY
}

json_log_line() {
  local action="$1" source="$2" dest="$3" size_bytes="${4:-0}" status="$5" error_msg="${6:-}"
  mkdir -p "$(dirname "$LOG_PATH")"
  json_escape_py "$action" "$source" "$dest" "$size_bytes" "$status" "$error_msg" >>"$LOG_PATH"
}

ssh_brain_once() {
  local cmd="$1"
  ssh -o BatchMode=yes -o ConnectTimeout=15 "$BRAIN_SSH" "$cmd"
}

ssh_brain_retry() {
  local cmd="$1"
  local ec=0
  ssh_brain_once "$cmd" || ec=$?
  if [[ "$ec" -eq 0 ]]; then
    return 0
  fi
  echo "warning: SSH failed (exit $ec), retrying once..." >&2
  sleep 1
  ssh_brain_once "$cmd" || {
    echo "error: SSH to $BRAIN_SSH failed after retry" >&2
    return 1
  }
}

verify_brain_reachable() {
  if ! ssh_brain_retry 'test -d "/Users/jarvisbrain/jarvis" && echo OK'; then
    return 1
  fi
}

run_audit_capture() {
  if [[ ! -f "$AUDIT_SCRIPT" ]]; then
    echo "error: audit script not found: $AUDIT_SCRIPT" >&2
    return 1
  fi
  bash "$AUDIT_SCRIPT" --all
}

# Parse KEEP and SAFE_TO_ARCHIVE sections from full audit stdout (verdict logic unchanged).
extract_keep_paths() {
  awk '
    /^=== KEEP \(/ { keep=1; next }
    keep && /^=== SAFE_TO_ARCHIVE \(/ { exit }
    keep && /^=== / { exit }
    keep && NF && $0 !~ /^#/ { print }
  '
}

extract_safe_paths() {
  awk '
    /^=== SAFE_TO_ARCHIVE \(/ { safe=1; next }
    safe && /^=== / && $0 !~ /^=== SAFE_TO_ARCHIVE/ { exit }
    safe && ($0 ~ /^# (directories|files)$/ || $0 == "(none)" || NF == 0) { next }
    safe && NF { print }
  '
}

path_in_keep_list() {
  local needle="$1"
  local k
  for k in "${KEEP_PATHS[@]:-}"; do
    [[ "$k" == "$needle" ]] && return 0
  done
  return 1
}

refuse_if_keep() {
  local rel="$1" ctx="$2"
  if path_in_keep_list "$rel"; then
    echo "error: refuse $ctx '$rel': audit verdict is KEEP" >&2
    return 1
  fi
  return 0
}

# Remote size: bytes (du -sk for dirs, stat for files). Paths are fixed constants / controlled lists only.
brain_path_exists() {
  local rel="$1"
  local out q cmd
  q=$(printf '%q' "$rel")
  cmd=$(cat <<ENDOFCMD
set -euo pipefail
rel=${q}
root='/Users/jarvisbrain/jarvis'
p="\${root}/\${rel}"
if [[ -e "\$p" ]]; then echo yes; else echo no; fi
ENDOFCMD
)
  out="$(ssh_brain_retry "$cmd")"
  [[ "${out//$'\r'/}" == "yes" ]]
}

brain_size_bytes() {
  local rel="$1" out q cmd
  q=$(printf '%q' "$rel")
  cmd=$(cat <<ENDOFCMD
set -euo pipefail
rel=${q}
root='/Users/jarvisbrain/jarvis'
p="\${root}/\${rel}"
if [[ -d "\$p" ]]; then
  kb=\$(du -sk "\$p" 2>/dev/null | cut -f1)
  [[ -z "\$kb" ]] && kb=0
  echo \$(( kb * 1024 ))
elif [[ -f "\$p" ]]; then
  stat -f%z "\$p" 2>/dev/null || echo 0
else
  echo 0
fi
ENDOFCMD
)
  if ! out="$(
    ssh_brain_retry "$cmd" 2>/dev/null
  )"; then
    printf '%s' "0"
    return 0
  fi
  out="${out//$'\r'/}"
  out="${out//$'\n'/}"
  printf '%s' "$out"
}

# Sort paths: longest first (handles nested audit keys).
sort_paths_deepest_first() {
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" ]] && continue
    printf '%s\n' "$line"
  done | awk '{ print length($0), $0 }' | sort -rn | cut -d' ' -f2-
}

dedupe_paths() {
  sort -u
}

build_plan_arrays() {
  local audit_out="$1"
  local safe_raw keep_raw
  KEEP_PATHS=()
  SAFE_MV_RELS=()
  ADDITIONAL_MV_RELS=()
  DELETE_RELS=()

  keep_raw="$(printf '%s\n' "$audit_out" | extract_keep_paths)"
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" ]] && continue
    KEEP_PATHS+=("$line")
  done <<<"$keep_raw"

  safe_raw="$(printf '%s\n' "$audit_out" | extract_safe_paths)"
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" ]] && continue
    SAFE_MV_RELS+=("$line")
  done <<<"$safe_raw"

  local a
  for a in "${ADDITIONAL_ITEMS[@]}"; do
    ADDITIONAL_MV_RELS+=("$a")
  done
  for a in "${DELETE_ITEMS[@]}"; do
    DELETE_RELS+=("$a")
  done
}

# Table: path | action | size | verdict-source
print_plan_table() {
  local rel size src verdict
  local -a rows=()
  TOTAL_SIZE_BYTES=0

  for rel in "${SAFE_MV_RELS[@]}"; do
    verdict="audit"
    if ! brain_path_exists "$rel"; then
      echo "warning: SAFE_TO_ARCHIVE path missing on Brain, skipping row: $rel" >&2
      continue
    fi
    size="$(brain_size_bytes "$rel" | tr -d '\r')"
    [[ -z "$size" ]] && size=0
    TOTAL_SIZE_BYTES=$((TOTAL_SIZE_BYTES + size))
    rows+=("$rel|MV|$size|$verdict")
  done

  for rel in "${ADDITIONAL_MV_RELS[@]}"; do
    verdict="additional"
    if ! refuse_if_keep "$rel" "additional item"; then
      continue
    fi
    if ! brain_path_exists "$rel"; then
      echo "warning: additional path missing on Brain, skipping: $rel" >&2
      continue
    fi
    size="$(brain_size_bytes "$rel" | tr -d '\r')"
    [[ -z "$size" ]] && size=0
    TOTAL_SIZE_BYTES=$((TOTAL_SIZE_BYTES + size))
    rows+=("$rel|MV|$size|$verdict")
  done

  for rel in "${DELETE_RELS[@]}"; do
    verdict="delete-outright"
    if ! brain_path_exists "$rel"; then
      echo "warning: delete target missing on Brain, skipping: $rel" >&2
      continue
    fi
    size="$(brain_size_bytes "$rel" | tr -d '\r')"
    [[ -z "$size" ]] && size=0
    TOTAL_SIZE_BYTES=$((TOTAL_SIZE_BYTES + size))
    rows+=("$rel|RM|$size|$verdict")
  done

  echo ""
  echo "path | action | size_bytes | verdict-source"
  printf '%s\n' "${rows[@]}" | column -t -s '|'
  echo ""
  local n=${#rows[@]}
  echo "TOTAL: items=$n total_size_bytes=$TOTAL_SIZE_BYTES"
}

collect_mv_list() {
  MV_RELS=()
  local rel
  for rel in "${SAFE_MV_RELS[@]}"; do
    refuse_if_keep "$rel" "SAFE item" || exit 1
    MV_RELS+=("$rel")
  done
  for rel in "${ADDITIONAL_MV_RELS[@]}"; do
    refuse_if_keep "$rel" "additional item" || exit 1
    MV_RELS+=("$rel")
  done
  # deepest-first unique
  local sorted
  sorted="$(printf '%s\n' "${MV_RELS[@]}" | dedupe_paths | sort_paths_deepest_first)"
  MV_RELS=()
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" ]] && continue
    MV_RELS+=("$line")
  done <<<"$sorted"
}

remote_mkdir_p() {
  local dir="$1" q
  q=$(printf '%q' "$dir")
  ssh_brain_retry "mkdir -p ${q}"
}

remote_mv() {
  local src="$1" dst="$2" qs qd
  qs=$(printf '%q' "$src")
  qd=$(printf '%q' "$dst")
  ssh_brain_retry "set -euo pipefail; mv ${qs} ${qd}"
}

remote_rm_rf() {
  local target="$1" q
  q=$(printf '%q' "$target")
  ssh_brain_retry "rm -rf ${q}"
}

write_archived_md_initial() {
  local path="$1"
  local content b64 q cmd
  content='# Archived 2026-04-21

## Context
jarvis-core superseded by jarvis-alpha. No live service references any file in this archive.

## Git tag
archived-2026-04-21 on github.com/kphaas/jarvis-core at commit 73c68cb546eeab9450408c8655a17955f1253ba5

## Cool-off
Delete this directory permanently after 2026-05-21 (TD-132). That gives 30 days to discover
anything wrongly archived. If any service breaks referencing a path here, mv it back.

## Audit source
See jarvis-alpha/scripts/audit_jarvis_core.sh for the verdict logic.
Manifest: jarvis-alpha/logs/archive_jarvis_core_20260421.log
'
  b64=$(printf '%s' "$content" | base64)
  q=$(printf '%q' "$path")
  cmd="echo ${b64} | base64 -d > ${q}"
  ssh_brain_retry "$cmd"
}

append_archived_md_summary() {
  local path="$1" moved="$2" ts="$3"
  local content b64 q cmd
  content="

## Archive completed
- Moved: ${moved} items
- Completed at: ${ts}
"
  b64=$(printf '%s' "$content" | base64)
  q=$(printf '%q' "$path")
  cmd="echo ${b64} | base64 -d >> ${q}"
  ssh_brain_retry "$cmd"
}

run_sanity_checks() {
  local cmd
  echo ""
  echo "=== Sanity checks (Brain) ==="
  cmd=$(cat <<'ENDOFCMD'
set +e
echo "--- ls ~/jarvis/ ---"
ls -la "$HOME/jarvis" 2>&1
echo ""
echo "--- health ---"
curl -fsS "https://jarvis-brain.tail40ed36.ts.net:8186/health" 2>&1 || echo "(curl failed)"
echo ""
echo "--- launchctl state ---"
launchctl print "gui/$(id -u)/com.jarvis.alpha.brain" 2>&1 | grep state || true
echo ""
echo "--- stack process count (temporal|loki|ollama) ---"
n=$(ps -ax 2>/dev/null | grep -E "temporal-server|loki|ollama" | grep -v grep | wc -l | tr -d ' ')
echo "count=$n (expect >= 3)"
ENDOFCMD
)
  ssh_brain_retry "$cmd"
}

do_execute() {
  local audit_out ts_human
  echo "Running audit (reuse verdict logic)..."
  audit_out="$(run_audit_capture)"
  build_plan_arrays "$audit_out"
  collect_mv_list

  mkdir -p "$(dirname "$LOG_PATH")"
  : >"$LOG_PATH"

  if [[ "$EXECUTE_YES" -ne 1 ]]; then
    read -r -p "Execute archive on Brain? Y/n " ans || true
    ans_lc="$(printf '%s' "${ans:-}" | tr '[:upper:]' '[:lower:]')"
    if [[ "$ans_lc" == "n" || "$ans_lc" == "no" ]]; then
      echo "Aborted."
      exit 0
    fi
  fi

  EXECUTE_STARTED=1

  remote_mkdir_p "$ARCHIVE_ROOT"
  remote_mkdir_p "$ARCHIVE_ROOT/_DELETED_caches"
  write_archived_md_initial "$ARCHIVE_ROOT/ARCHIVED.md"

  MOVED_COUNT=0
  ERR_COUNT=0
  DELETED_COUNT=0
  TOTAL_SIZE_BYTES=0

  local rel src dst sz ts_human err
  ts_human="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

  for rel in "${MV_RELS[@]}"; do
    src="$JARVIS_ROOT/$rel"
    dst="$ARCHIVE_ROOT/$rel"
    q=$(printf '%q' "$rel")
    cmd=$(cat <<ENDOFCMD
set -euo pipefail
rel=${q}
root='/Users/jarvisbrain/jarvis'
[[ -e "\${root}/\${rel}" ]] && echo yes || echo no
ENDOFCMD
)
    ex="$(ssh_brain_retry "$cmd")" || {
      ERR_COUNT=$((ERR_COUNT + 1))
      json_log_line "mv" "$src" "$dst" 0 "error" "ssh check failed"
      continue
    }
    ex="${ex//$'\r'/}"
    ex="${ex//$'\n'/}"
    if [[ "$ex" != "yes" ]]; then
      echo "warning: source missing, skipping mv: $rel" >&2
      json_log_line "mv" "$src" "$dst" 0 "skipped" "source missing"
      continue
    fi

    sz="$(brain_size_bytes "$rel" | tr -d '\r')"
    [[ -z "$sz" ]] && sz=0
    TOTAL_SIZE_BYTES=$((TOTAL_SIZE_BYTES + sz))

    remote_mkdir_p "$(dirname "$dst")"
    ts_human="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    if remote_mv "$src" "$dst"; then
      MOVED_COUNT=$((MOVED_COUNT + 1))
      echo "moved: $rel (${sz} bytes) @ $ts_human"
      json_log_line "mv" "$src" "$dst" "$sz" "ok" ""
      echo "MANIFEST_MV: $src -> $dst" >>"$LOG_PATH"
      echo "LOG: $src -> $dst size_bytes=$sz ts=$ts_human" >&2
    else
      err="mv failed"
      ERR_COUNT=$((ERR_COUNT + 1))
      echo "warning: $err for $rel" >&2
      json_log_line "mv" "$src" "$dst" "$sz" "error" "$err"
    fi
  done

  local drel dsrc
  local del_log="$ARCHIVE_ROOT/_DELETED_caches/deleted.log"
  for drel in "${DELETE_RELS[@]}"; do
    dsrc="$JARVIS_ROOT/$drel"
    if ! brain_path_exists "$drel"; then
      echo "warning: delete target missing, skipping: $drel" >&2
      json_log_line "rm" "$dsrc" "" 0 "skipped" "missing"
      continue
    fi
    sz="$(brain_size_bytes "$drel" | tr -d '\r')"
    [[ -z "$sz" ]] && sz=0
    TOTAL_SIZE_BYTES=$((TOTAL_SIZE_BYTES + sz))
    ts_human="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    ql=$(printf '%q' "$del_log")
    qds=$(printf '%q' "$dsrc")
    qr=$(printf '%q' "$drel")
    qsz=$(printf '%q' "$sz")
    qts=$(printf '%q' "$ts_human")
    cmd=$(cat <<ENDOFCMD
set -euo pipefail
log=${ql}
src=${qds}
rel=${qr}
sz=${qsz}
ts=${qts}
printf '%s\t%s\t%s\t%s\n' "\$ts" "\$rel" "\$src" "\$sz" >>"\$log"
ENDOFCMD
)
    ssh_brain_retry "$cmd"
    if remote_rm_rf "$dsrc"; then
      DELETED_COUNT=$((DELETED_COUNT + 1))
      echo "deleted: $drel (${sz} bytes)"
      json_log_line "rm" "$dsrc" "$ARCHIVE_ROOT/_DELETED_caches" "$sz" "ok" ""
    else
      ERR_COUNT=$((ERR_COUNT + 1))
      json_log_line "rm" "$dsrc" "" "$sz" "error" "rm failed"
    fi
  done

  append_archived_md_summary "$ARCHIVE_ROOT/ARCHIVED.md" "$MOVED_COUNT" "$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  run_sanity_checks

  echo ""
  echo "SUMMARY: moved=$MOVED_COUNT errors=$ERR_COUNT deleted=$DELETED_COUNT total_size_bytes=$TOTAL_SIZE_BYTES path=$ARCHIVE_ROOT log=$LOG_PATH"
}

do_rollback() {
  if [[ ! -f "$LOG_PATH" ]]; then
    echo "error: log not found: $LOG_PATH" >&2
    exit 1
  fi
  local line src dst n rest rb_tmp
  n=0
  mkdir -p "$(dirname "$LOG_PATH")"
  rb_tmp="$(mktemp "${TMPDIR:-/tmp}/archive_jarvis_core_rb.XXXXXX")"
  {
    while IFS= read -r line; do
      [[ -z "$line" ]] && continue
      rest="${line#MANIFEST_MV: }"
      dst="${rest##* -> }"
      printf '%010d\t%s\n' "${#dst}" "$line"
    done < <(grep '^MANIFEST_MV: ' "$LOG_PATH" || true)
  } | sort -t $'\t' -rn -k1,1 | cut -f2- >"$rb_tmp"

  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    rest="${line#MANIFEST_MV: }"
    src="${rest%% -> *}"
    dst="${rest##* -> }"
    if [[ -z "$src" || -z "$dst" ]]; then
      continue
    fi
    qd=$(printf '%q' "$dst")
    qs=$(printf '%q' "$src")
    cmd=$(cat <<ENDOFCMD
set -euo pipefail
dst=${qd}
src=${qs}
if [[ ! -e "\$dst" ]]; then
  echo "missing_dst:\$dst" >&2
  exit 2
fi
mkdir -p "\$(dirname "\$src")"
mv "\$dst" "\$src"
ENDOFCMD
)
    if ssh_brain_retry "$cmd"
    then
      n=$((n + 1))
      echo "restored: $dst -> $src"
      json_log_line "rollback_mv" "$dst" "$src" 0 "ok" ""
    else
      echo "warning: rollback failed for $dst" >&2
      json_log_line "rollback_mv" "$dst" "$src" 0 "error" "rollback mv failed"
    fi
  done <"$rb_tmp"
  rm -f "$rb_tmp"

  qa=$(printf '%q' "$ARCHIVE_ROOT")
  cmd=$(cat <<ENDOFCMD
set -euo pipefail
ar=${qa}
if [[ -d "\$ar" ]]; then
  if [[ -z "\$(ls -A "\$ar" 2>/dev/null)" ]]; then
    rm -rf "\$ar"
  fi
fi
ENDOFCMD
)
  ssh_brain_retry "$cmd"

  echo "rollback restored count: $n"
}

print_exit_summary() {
  [[ "$SUMMARY_PRINTED" -eq 1 ]] && return 0
  if [[ "${MODE:-}" == "execute" && "${EXECUTE_STARTED:-0}" -eq 1 ]]; then
    SUMMARY_PRINTED=1
    echo "(exit trap) moved=$MOVED_COUNT errors=$ERR_COUNT deleted=$DELETED_COUNT total_size_bytes=$TOTAL_SIZE_BYTES path=$ARCHIVE_ROOT log=$LOG_PATH" >&2
  fi
}

trap 'print_exit_summary' EXIT

while [[ $# -gt 0 ]]; do
  case "$1" in
    --plan) MODE="plan"; shift ;;
    --execute) MODE="execute"; shift ;;
    --rollback) MODE="rollback"; shift ;;
    --yes) EXECUTE_YES=1; shift ;;
    -h|--help) usage ;;
    *) echo "unknown arg: $1" >&2; usage ;;
  esac
done

[[ -z "${MODE:-}" ]] && usage

KEEP_PATHS=()
SAFE_MV_RELS=()
ADDITIONAL_MV_RELS=()
DELETE_RELS=()
MV_RELS=()

case "$MODE" in
  plan)
    verify_brain_reachable || exit 1
    echo "Running audit: bash scripts/audit_jarvis_core.sh --all"
    audit_out="$(run_audit_capture)"
    build_plan_arrays "$audit_out"
    print_plan_table
    ;;
  execute)
    verify_brain_reachable || exit 1
    do_execute
    SUMMARY_PRINTED=1
    ;;
  rollback)
    do_rollback
    SUMMARY_PRINTED=1
    ;;
esac
