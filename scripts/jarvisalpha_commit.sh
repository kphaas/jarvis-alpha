#!/usr/bin/env bash
export GIT_TERMINAL_PROMPT=0
set -e

REPO_ROOT="${HOME}/jarvis-alpha"
cd "$REPO_ROOT"

# 1. Format Python in brain/ when any .py file is part of the working tree changes.
py_changed=false
if git diff --name-only HEAD | grep -qE '\.py$'; then
  py_changed=true
fi
if git ls-files -o --exclude-standard | grep -qE '\.py$'; then
  py_changed=true
fi
if [[ "$py_changed" == true ]]; then
  ruff format brain/
fi

# 2–3. UI build and optional deploy of dist/
if [[ -d "$REPO_ROOT/ui/src" ]]; then
  (cd "$REPO_ROOT/ui" && npm run build) || {
    echo "UI build failed — aborting commit" >&2
    exit 1
  }
  if [[ -d "$REPO_ROOT/ui/dist" ]]; then
    rsync -az --delete "$REPO_ROOT/ui/dist/" jarvisendpoint@100.87.223.31:~/jarvis-alpha/ui/dist/ || {
      echo "Warning: rsync to jarvisendpoint failed (continuing)." >&2
    }
  fi
fi

git add -A
if git diff --cached --quiet; then
  echo "Nothing to commit"
  exit 0
fi

git commit -m "$1"
git pull origin main --rebase
git push origin main

echo "jarvis-alpha commit complete: $(git rev-parse --short HEAD)"

ssh jarvisbrain@100.64.166.22 'bash ~/jarvis-alpha/scripts/jarvisalpha_pull.sh'
