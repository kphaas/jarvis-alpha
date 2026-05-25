#!/bin/bash
# Safe Sandbox pull used by jarvisalpha_deploy.sh.
#
# Sandbox often receives agent-authored files before Air commits the same path.
# If an untracked file would be overwritten by origin/main, delete it only when
# its bytes already match origin/main. Divergent local files fail closed.

set -uo pipefail

REPO_DIR="${JARVIS_ALPHA_REPO_DIR:-${HOME}/jarvis-alpha}"

cd "$REPO_DIR" || {
  echo "ERROR: repo not found at $REPO_DIR" >&2
  exit 1
}

git fetch origin main --quiet
git switch main --quiet

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "ERROR: Sandbox has tracked local changes; refusing to pull." >&2
  git status --short >&2
  exit 2
fi

while IFS= read -r -d '' path; do
  if git cat-file -e "origin/main:${path}" 2>/dev/null; then
    tmp="$(mktemp)"
    git show "origin/main:${path}" > "$tmp"
    if cmp -s "$path" "$tmp"; then
      rm -f "$path"
    else
      rm -f "$tmp"
      echo "ERROR: Sandbox untracked collision differs from origin/main: $path" >&2
      exit 3
    fi
    rm -f "$tmp"
  fi
done < <(git ls-files -z -o --exclude-standard)

git pull --ff-only origin main --quiet
git rev-parse --short HEAD
