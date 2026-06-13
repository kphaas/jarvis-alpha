#!/usr/bin/env bash
# Sync the private jarvis-personality vault on Brain without using HTTPS tokens.

set -euo pipefail

VAULT_ROOT="${JARVIS_PERSONALITY_VAULT:-${SPARK_PERSONALITY_VAULT:-${HOME}/jarvis-personality}}"
BRANCH="${JARVIS_PERSONALITY_BRANCH:-main}"
DEFAULT_GIT_URL="github-jarvis-personality:kphaas/jarvis-personality.git"
GIT_URL="${JARVIS_PERSONALITY_GIT_URL:-$DEFAULT_GIT_URL}"

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

validate_required_files() {
  local root="$1"
  local missing=0
  for rel in \
    "spark/principals/ken/voice.md" \
    "spark/principals/ken/sources.yml" \
    "auto/interfaces/spark_context.yml"; do
    if [ ! -f "${root}/${rel}" ]; then
      printf 'missing required personality file: %s\n' "$rel" >&2
      missing=1
    fi
  done
  [ "$missing" -eq 0 ] || fail "personality vault sync incomplete"
}

if [ ! -d "$VAULT_ROOT/.git" ]; then
  mkdir -p "$(dirname "$VAULT_ROOT")"
  GIT_TERMINAL_PROMPT=0 git clone --branch "$BRANCH" "$GIT_URL" "$VAULT_ROOT"
fi

cd "$VAULT_ROOT"

if ! git remote get-url origin >/dev/null 2>&1; then
  git remote add origin "$GIT_URL"
fi

origin_url="$(git remote get-url origin)"
case "$origin_url" in
  https://github.com/kphaas/jarvis-personality.git|https://kphaas:*@github.com/kphaas/jarvis-personality.git)
    git remote set-url origin "$GIT_URL"
    ;;
esac

if [ -n "$(git status --porcelain)" ]; then
  git status --short >&2
  fail "personality vault has local changes; stash or commit before sync"
fi

GIT_TERMINAL_PROMPT=0 git fetch origin "$BRANCH"
GIT_TERMINAL_PROMPT=0 git merge --ff-only FETCH_HEAD

validate_required_files "$VAULT_ROOT"

head_short="$(git rev-parse --short HEAD)"
printf 'SYNCED personality_vault=%s branch=%s head=%s\n' "$VAULT_ROOT" "$BRANCH" "$head_short"
