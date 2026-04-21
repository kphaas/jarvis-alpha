#!/usr/bin/env bash
# Audit references to ~/jarvis/ (jarvis-core) paths from Brain and local repos.

set -o pipefail

BRAIN_SSH="jarvisbrain@jarvis-brain.tail40ed36.ts.net"
REPOS=(/Users/swetagurnani/jarvis-alpha /Users/swetagurnani/jarvis-forge /Users/swetagurnani/jarvis-family /Users/swetagurnani/jarvis-standards)
FILE_TYPES=(--include="*.py" --include="*.sh" --include="*.ts" --include="*.tsx" --include="*.yaml" --include="*.yml" --include="*.plist" --include="*.json" --include="*.mdc")
EXCLUDE_DIRS=(--exclude-dir=".venv" --exclude-dir=".git" --exclude-dir="node_modules" --exclude-dir="dist" --exclude-dir="build" --exclude-dir="__pycache__")

REPO_LABELS=(alpha forge family standards)

usage() {
  echo "Usage: $0 [--details] --all | $0 [--details] PATH [PATH...]" >&2
  exit 1
}

regex_escape_egrep() {
  sed -e 's/[][\\.^$*+?{}()|]/\\&/g' <<<"$1"
}

# Regex alternation contains "|"; sshd runs the remote command under sh -c, which splits on |.
# Pass search regex via base64 and decode inside the remote bash script (stdin), not argv.
rx_b64_encode() {
  printf '%s' "$1" | base64 | tr -d '\n'
}

normalize_path_key() {
  local raw="$1"
  local p="$raw"
  if [[ -z "$p" ]]; then
    echo ""
    return
  fi
  p="${p/#\~/$HOME}"
  if [[ "$p" == /Users/jarvisbrain/jarvis/* ]]; then
    p="${p#/Users/jarvisbrain/jarvis/}"
  elif [[ "$p" == "$HOME/jarvis/"* ]]; then
    p="${p#$HOME/jarvis/}"
  elif [[ "$p" == */jarvis/* ]]; then
    p="${p##*/jarvis/}"
  elif [[ "$p" == jarvis/* ]]; then
    p="${p#jarvis/}"
  fi
  p="${p#/}"
  p="${p%/}"
  printf '%s' "$p"
}

# SEARCH_PATTERNS: four alternates for grep -E (see build_search_regex).
build_search_regex() {
  local pk="$1"
  local p1 p2 p3 p4
  p1="$(regex_escape_egrep "/Users/jarvisbrain/jarvis/${pk}")"
  p2="$(regex_escape_egrep "~/jarvis/${pk}")"
  p3="$(regex_escape_egrep "\$HOME/jarvis/${pk}")"
  p4="$(regex_escape_egrep "jarvis/${pk}")"
  printf '%s' "${p1}|${p2}|${p3}|${p4}"
}

is_self_path_in_repo() {
  local file="$1"
  local repo="$2"
  local pk="$3"
  local base="${repo}/${pk}"
  if [[ -d "$base" ]]; then
    [[ "$file" == "$base" || "$file" == "$base"/* ]]
  elif [[ -f "$base" ]]; then
    [[ "$file" == "$base" ]]
  else
    return 1
  fi
}

# CHECK 4 — Source repos (grep -rln-style file list per repo).
count_repo_matches() {
  local pk="$1"
  local repo="$2"
  local rx="$3"
  local tmp n
  if [[ ! -d "$repo" ]]; then
    echo 0
    return
  fi
  tmp="$(mktemp "${TMPDIR:-/tmp}/audit_jarvis_core.XXXXXX")"
  if ! grep -REl "${FILE_TYPES[@]}" "${EXCLUDE_DIRS[@]}" "$rx" "$repo" 2>/dev/null >"$tmp"; then
    rm -f "$tmp"
    echo 0
    return
  fi
  n=0
  while IFS= read -r f || [[ -n "$f" ]]; do
    [[ -z "$f" ]] && continue
    if is_self_path_in_repo "$f" "$repo" "$pk"; then
      continue
    fi
    n=$((n + 1))
  done <"$tmp"
  rm -f "$tmp"
  echo "$n"
}

# CHECK 1 — Brain LaunchAgents (com.jarvis.*.plist, exclude .bak).
check_launchagents() {
  local rx="$1"
  local b64
  b64="$(rx_b64_encode "$rx")"
  ssh -o BatchMode=yes -o ConnectTimeout=15 "$BRAIN_SSH" bash -s <<EOF
b64='$b64'
rx=\$(printf '%s' "\$b64" | base64 -d 2>/dev/null || printf '%s' "\$b64" | base64 -D)
set +e
shopt -s nullglob
count=0
for plist in "\$HOME/Library/LaunchAgents"/com.jarvis.*.plist; do
  [[ -f "\$plist" ]] || continue
  case "\$plist" in
    *.bak) continue ;;
  esac
  bn=\$(basename "\$plist")
  case "\$bn" in
    *".bak"*) continue ;;
  esac
  n=\$(grep -ciE "\$rx" "\$plist" 2>/dev/null || true)
  [[ -z "\$n" || "\$n" -eq 0 ]] && continue
  count=\$((count + n))
  grep -niE "\$rx" "\$plist" 2>/dev/null | while IFS= read -r gline || [[ -n "\$gline" ]]; do
    [[ -z "\$gline" ]] && continue
    printf '%s|%s\n' "\$plist" "\$gline"
  done
done
printf 'COUNT:%s\n' "\$count"
EOF
}

# CHECK 2 — Brain crontab.
check_crontab() {
  local rx="$1"
  local b64
  b64="$(rx_b64_encode "$rx")"
  ssh -o BatchMode=yes -o ConnectTimeout=15 "$BRAIN_SSH" bash -s <<EOF
b64='$b64'
rx=\$(printf '%s' "\$b64" | base64 -d 2>/dev/null || printf '%s' "\$b64" | base64 -D)
set +e
crontab -l 2>/dev/null | grep -v grep | grep -Eic "\$rx" || true
EOF
}

# CHECK 3 — Brain processes.
check_processes() {
  local rx="$1"
  local b64
  b64="$(rx_b64_encode "$rx")"
  ssh -o BatchMode=yes -o ConnectTimeout=15 "$BRAIN_SSH" bash -s <<EOF
b64='$b64'
rx=\$(printf '%s' "\$b64" | base64 -d 2>/dev/null || printf '%s' "\$b64" | base64 -D)
set +e
ps -axww 2>/dev/null | grep -v grep | grep -Eic "\$rx" || true
EOF
}

brain_path_state() {
  local pk="$1"
  ssh -o BatchMode=yes -o ConnectTimeout=15 "$BRAIN_SSH" bash -s -- "$pk" <<'REMOTE'
set +e
if [[ -e "$HOME/jarvis/$1" ]]; then
  echo OK
else
  echo MISSING
fi
REMOTE
}

brain_path_is_dir() {
  local pk="$1"
  ssh -o BatchMode=yes -o ConnectTimeout=15 "$BRAIN_SSH" bash -s -- "$pk" <<'REMOTE'
if [[ -d "$HOME/jarvis/$1" ]]; then echo dir; elif [[ -f "$HOME/jarvis/$1" ]]; then echo file; else echo unknown; fi
REMOTE
}

list_all_path_keys() {
  ssh -o BatchMode=yes -o ConnectTimeout=15 "$BRAIN_SSH" bash -s <<'EOS'
set -euo pipefail
shopt -s nullglob
for item in "$HOME/jarvis"/*; do
  [[ -e "$item" ]] || continue
  rel="${item#$HOME/jarvis/}"
  printf '%s\n' "$rel"
done
for item in "$HOME/jarvis/scripts"/*; do
  [[ -e "$item" ]] || continue
  rel="scripts/${item#$HOME/jarvis/scripts/}"
  printf '%s\n' "$rel"
done
EOS
}

ssh_brain_details_cron() {
  local rx="$1"
  local b64
  b64="$(rx_b64_encode "$rx")"
  ssh -o BatchMode=yes -o ConnectTimeout=15 "$BRAIN_SSH" bash -s <<EOF
b64='$b64'
rx=\$(printf '%s' "\$b64" | base64 -d 2>/dev/null || printf '%s' "\$b64" | base64 -D)
set +e
crontab -l 2>/dev/null | grep -v grep | grep -Ei "\$rx" || true
EOF
}

ssh_brain_details_ps() {
  local rx="$1"
  local b64
  b64="$(rx_b64_encode "$rx")"
  ssh -o BatchMode=yes -o ConnectTimeout=15 "$BRAIN_SSH" bash -s <<EOF
b64='$b64'
rx=\$(printf '%s' "\$b64" | base64 -d 2>/dev/null || printf '%s' "\$b64" | base64 -D)
set +e
ps -axww 2>/dev/null | grep -v grep | grep -Ei "\$rx" || true
EOF
}

DETAILS=0
ALL_MODE=0
PATHS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --details) DETAILS=1; shift ;;
    --all) ALL_MODE=1; shift ;;
    -h|--help) usage ;;
    *) PATHS+=("$1"); shift ;;
  esac
done

if [[ "$ALL_MODE" -eq 1 && ${#PATHS[@]} -gt 0 ]]; then
  echo "error: do not combine --all with PATH arguments" >&2
  exit 1
fi

if [[ "$ALL_MODE" -eq 0 && ${#PATHS[@]} -eq 0 ]]; then
  usage
fi

AUDIT_KEYS=()
if [[ "$ALL_MODE" -eq 1 ]]; then
  enum_out=""
  if ! enum_out="$(list_all_path_keys 2>/dev/null)"; then
    echo "error: could not enumerate paths on Brain (SSH failed)" >&2
    exit 1
  fi
  if [[ -z "$enum_out" ]]; then
    echo "error: empty enumeration from Brain (SSH failed or empty ~/jarvis)" >&2
    exit 1
  fi
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" ]] && continue
    AUDIT_KEYS+=("$line")
  done < <(printf '%s\n' "$enum_out" | sort -u)
else
  for raw in "${PATHS[@]}"; do
    nk="$(normalize_path_key "$raw")"
    if [[ -z "$nk" ]]; then
      echo "warning: skipping empty path" >&2
      continue
    fi
    AUDIT_KEYS+=("$nk")
  done
fi

ROWS=()
VERDICTS=()
KEEP_EVIDENCE=()

for pk in "${AUDIT_KEYS[@]}"; do
  [[ -z "$pk" ]] && continue

  verdict="SAFE_TO_ARCHIVE"
  la_n=0 cron_n=0 proc_n=0
  c_alpha=0 c_forge=0 c_family=0 c_standards=0
  sources=()
  ssh_fail=0

  RX="$(build_search_regex "$pk")"

  bp_state=""
  if ! bp_state="$(brain_path_state "$pk" 2>/dev/null)"; then
    echo "error: SSH failed checking ~/jarvis/$pk on Brain" >&2
    verdict="SSH_FAIL"
    ssh_fail=1
    ROWS+=("$pk | LA:0 | CRON:0 | PROC:0 | CODE:alpha=0,forge=0,family=0,standards=0 | $verdict")
    VERDICTS+=("$pk|$verdict")
    continue
  fi
  bp_state="${bp_state//$'\r'/}"
  bp_state="${bp_state//$'\n'/}"
  if [[ "$bp_state" != "OK" ]]; then
    verdict="MISSING"
    ROWS+=("$pk | LA:0 | CRON:0 | PROC:0 | CODE:alpha=0,forge=0,family=0,standards=0 | $verdict")
    VERDICTS+=("$pk|$verdict")
    continue
  fi

  la_out=""
  la_raw=""
  if ! la_raw="$(check_launchagents "$RX" 2>/dev/null)"; then
    echo "error: SSH failed during LaunchAgents check for path_key=$pk" >&2
    verdict="SSH_FAIL"
    ssh_fail=1
    la_n=0
  else
    la_n="$(echo "$la_raw" | sed -n 's/^COUNT://p' | tail -1)"
    [[ -z "$la_n" ]] && la_n=0
    la_out="$(echo "$la_raw" | sed '/^COUNT:/d')"
  fi

  if [[ "$ssh_fail" -eq 0 ]]; then
    cron_raw=""
    if ! cron_raw="$(check_crontab "$RX" 2>/dev/null)"; then
      echo "error: SSH failed during crontab check for path_key=$pk" >&2
      verdict="SSH_FAIL"
      ssh_fail=1
      cron_n=0
    else
      cron_n="$(echo "$cron_raw" | tr -d '\r' | head -1)"
      [[ -z "$cron_n" ]] && cron_n=0
    fi
  fi

  if [[ "$ssh_fail" -eq 0 ]]; then
    proc_raw=""
    if ! proc_raw="$(check_processes "$RX" 2>/dev/null)"; then
      echo "error: SSH failed during process check for path_key=$pk" >&2
      verdict="SSH_FAIL"
      ssh_fail=1
      proc_n=0
    else
      proc_n="$(echo "$proc_raw" | tr -d '\r' | head -1)"
      [[ -z "$proc_n" ]] && proc_n=0
    fi
  fi

  if [[ "$ssh_fail" -eq 0 ]]; then
    c_alpha="$(count_repo_matches "$pk" "${REPOS[0]}" "$RX")"
    c_forge="$(count_repo_matches "$pk" "${REPOS[1]}" "$RX")"
    c_family="$(count_repo_matches "$pk" "${REPOS[2]}" "$RX")"
    c_standards="$(count_repo_matches "$pk" "${REPOS[3]}" "$RX")"
  fi

  # VERDICT: KEEP if any check has hits; SAFE_TO_ARCHIVE if none; handled above for MISSING/SSH_FAIL.
  if [[ "$verdict" != "SSH_FAIL" ]]; then
    if [[ "$la_n" -gt 0 ]]; then sources+=("LA"); verdict="KEEP"; fi
    if [[ "$cron_n" -gt 0 ]]; then sources+=("CRON"); verdict="KEEP"; fi
    if [[ "$proc_n" -gt 0 ]]; then sources+=("PROC"); verdict="KEEP"; fi
    [[ "$c_alpha" -gt 0 ]] && { sources+=("alpha"); verdict="KEEP"; }
    [[ "$c_forge" -gt 0 ]] && { sources+=("forge"); verdict="KEEP"; }
    [[ "$c_family" -gt 0 ]] && { sources+=("family"); verdict="KEEP"; }
    [[ "$c_standards" -gt 0 ]] && { sources+=("standards"); verdict="KEEP"; }
  fi

  hit_src=""
  if [[ ${#sources[@]} -gt 0 ]]; then
    hit_src=" ($(IFS=,; echo "${sources[*]}"))"
  fi

  ROWS+=("$pk | LA:${la_n} | CRON:${cron_n} | PROC:${proc_n} | CODE:alpha=${c_alpha},forge=${c_forge},family=${c_family},standards=${c_standards} | ${verdict}${hit_src}")

  VERDICTS+=("$pk|$verdict")

  if [[ "$DETAILS" -eq 1 && "$verdict" == "KEEP" ]]; then
    ev="=== $pk ==="
    if [[ -n "$la_out" ]]; then
      ev+=$'\n'"[LaunchAgents]"$'\n'"$la_out"
    fi
    if [[ "$ssh_fail" -eq 0 && "$cron_n" -gt 0 ]]; then
      cr_ev="$(ssh_brain_details_cron "$RX" 2>/dev/null || true)"
      ev+=$'\n'"[crontab]"$'\n'"$cr_ev"
    fi
    if [[ "$ssh_fail" -eq 0 && "$proc_n" -gt 0 ]]; then
      pr_ev="$(ssh_brain_details_ps "$RX" 2>/dev/null || true)"
      ev+=$'\n'"[processes]"$'\n'"$pr_ev"
    fi
    ri=0
    for repo in "${REPOS[@]}"; do
      label="${REPO_LABELS[$ri]}"
      ri=$((ri + 1))
      [[ ! -d "$repo" ]] && continue
      tmp="$(mktemp "${TMPDIR:-/tmp}/audit_jarvis_core.XXXXXX")"
      if grep -REl "${FILE_TYPES[@]}" "${EXCLUDE_DIRS[@]}" "$RX" "$repo" 2>/dev/null >"$tmp"; then
        :
      fi
      while IFS= read -r f || [[ -n "$f" ]]; do
        [[ -z "$f" ]] && continue
        if is_self_path_in_repo "$f" "$repo" "$pk"; then
          continue
        fi
        ev+=$'\n'"[$label] $f"
      done <"$tmp"
      rm -f "$tmp"
    done
    KEEP_EVIDENCE+=("$ev")
  fi
done

{
  printf '%s\n' "${ROWS[@]}" | column -t -s '|'
  echo ""
  keep_list=()
  safe_list=()
  for v in "${VERDICTS[@]}"; do
    p="${v%%|*}"
    ver="${v#*|}"
    case "$ver" in
      KEEP) keep_list+=("$p") ;;
      SAFE_TO_ARCHIVE) safe_list+=("$p") ;;
    esac
  done
  echo "=== KEEP (${#keep_list[@]}) ==="
  printf '%s\n' "${keep_list[@]}"
  echo ""
  echo "=== SAFE_TO_ARCHIVE (${#safe_list[@]}) ==="
  safe_dirs=()
  safe_files=()
  for p in "${safe_list[@]}"; do
    bt="$(brain_path_is_dir "$p" 2>/dev/null || echo unknown)"
    case "$bt" in
      dir) safe_dirs+=("$p") ;;
      file) safe_files+=("$p") ;;
      *) safe_dirs+=("$p") ;;
    esac
  done
  if [[ ${#safe_dirs[@]} -gt 0 ]]; then
    echo "# directories"
    printf '%s\n' "${safe_dirs[@]}"
  fi
  if [[ ${#safe_files[@]} -gt 0 ]]; then
    echo "# files"
    printf '%s\n' "${safe_files[@]}"
  fi
  if [[ ${#safe_list[@]} -eq 0 ]]; then
    echo "(none)"
  fi
}

if [[ "$DETAILS" -eq 1 && ${#KEEP_EVIDENCE[@]} -gt 0 ]]; then
  echo ""
  echo "=== DETAILS (KEEP paths) ==="
  printf '%s\n\n' "${KEEP_EVIDENCE[@]}"
fi
