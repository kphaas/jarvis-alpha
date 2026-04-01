#!/bin/bash
set -e

MSG="${1:-chore: update}"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

cd "$REPO_DIR"

ruff format brain/ gateway/ 2>/dev/null || true
git add -A
git commit -m "$MSG" || echo "Nothing to commit"
git pull origin main --rebase
git push origin main
