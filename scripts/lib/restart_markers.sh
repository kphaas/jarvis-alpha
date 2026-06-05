#!/usr/bin/env bash

# Helpers for restart decisions in pull-based deploys.
#
# A node can pull a commit before a service restart succeeds. Comparing only
# PREV_HEAD..NEW_HEAD then makes the next deploy believe nothing changed. These
# helpers compare the current commit to a per-service "last restarted" marker.

restart_marker_path() {
  local state_dir="$1"
  local service="$2"
  local safe_service
  safe_service=$(printf '%s' "$service" | tr -c '[:alnum:]_.-' '_')
  printf '%s/%s.head\n' "$state_dir" "$safe_service"
}

restart_marker_read() {
  local state_dir="$1"
  local service="$2"
  local marker
  marker=$(restart_marker_path "$state_dir" "$service")
  if [ -f "$marker" ]; then
    head -n 1 "$marker"
  fi
}

restart_marker_write() {
  local state_dir="$1"
  local service="$2"
  local commit="$3"
  local marker
  marker=$(restart_marker_path "$state_dir" "$service")
  mkdir -p "$state_dir"
  printf '%s\n' "$commit" > "$marker"
}

restart_marker_changed_files() {
  local repo_dir="$1"
  local marker_head="$2"
  local new_head="$3"
  local _fallback_changed_files="${4:-}"

  if [ -n "$marker_head" ] \
    && git -C "$repo_dir" cat-file -e "${marker_head}^{commit}" 2>/dev/null \
    && git -C "$repo_dir" merge-base --is-ancestor "$marker_head" "$new_head" 2>/dev/null; then
    if [ "$marker_head" = "$new_head" ]; then
      return 0
    fi
    git -C "$repo_dir" diff --name-only "${marker_head}..${new_head}"
    return
  fi

  # No usable marker means the repo may already be at the new commit without a
  # successful restart. Be conservative until this service writes a checkpoint.
  git -C "$repo_dir" ls-files
}
