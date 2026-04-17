#!/bin/bash
set -uo pipefail

REPO_DIR="${HOME}/jarvis-alpha"
if [ -f "${HOME}/jarvis/.secrets" ]; then
  SECRETS_FILE="${HOME}/jarvis/.secrets"
else
  SECRETS_FILE="${HOME}/.secrets"
fi

echo ""
echo "── JARVIS-ALPHA PULL ────────────────────────────────────"
echo "Node: $(hostname)"
echo "Time: $(date '+%Y-%m-%d %H:%M')"
echo ""

if [ ! -f "$SECRETS_FILE" ]; then
  echo "ERROR: secrets file not found at $SECRETS_FILE"
  exit 1
fi

set -a
source "$SECRETS_FILE"
set +a

if [ -z "${GITHUB_TOKEN:-}" ]; then
  echo "ERROR: GITHUB_TOKEN not set in secrets"
  exit 1
fi

if [ ! -d "$REPO_DIR" ]; then
  echo "Cloning jarvis-alpha for first time..."
  if ! git clone https://kphaas:${GITHUB_TOKEN}@github.com/kphaas/jarvis-alpha.git "$REPO_DIR"; then
    echo ""
    echo "❌ GIT CLONE FAILED — aborting."
    exit 1
  fi
else
  cd "$REPO_DIR"
  PREV_HEAD=$(git rev-parse --short HEAD 2>/dev/null || echo "")
  git config credential.helper ""
  GIT_TERMINAL_PROMPT=0 git remote set-url origin https://kphaas:${GITHUB_TOKEN}@github.com/kphaas/jarvis-alpha.git
  if ! GIT_TERMINAL_PROMPT=0 git pull origin main --rebase; then
    echo ""
    echo "❌ GIT PULL FAILED — aborting."
    echo "   Check: cd $REPO_DIR && git status"
    exit 1
  fi
fi

NEW_HEAD=$(git -C "$REPO_DIR" rev-parse --short HEAD)

if [ -n "${PREV_HEAD:-}" ] && [ "$PREV_HEAD" != "$NEW_HEAD" ]; then
  echo ""
  echo "── INCOMING COMMITS ─────────────────────────────────────"
  git -C "$REPO_DIR" log --no-merges --pretty=format:'%h  %s  (%an, %ar)' "${PREV_HEAD}..${NEW_HEAD}"
  echo ""
  echo ""
  echo "── CHURN ────────────────────────────────────────────────"
  git -C "$REPO_DIR" diff --shortstat "${PREV_HEAD}..${NEW_HEAD}"
  git -C "$REPO_DIR" diff --stat "${PREV_HEAD}..${NEW_HEAD}" | tail -n +1 | head -n 20
fi

echo ""
echo "✅ jarvis-alpha pulled — $NEW_HEAD"
echo "─────────────────────────────────────────────────────────"

echo ""
if [ "$(hostname -s)" = "jarvis-brain" ]; then
  echo "Running database migrations..."
  if ! bash "${REPO_DIR}/scripts/apply_migrations.sh"; then
    echo ""
    echo "❌ MIGRATION FAILED — aborting pull deploy."
    echo "   Services NOT restarted. Fix migration before retrying."
    exit 1
  fi
  echo "✅ Migrations applied"
else
  echo "ℹ️  Skipping migrations — not on Brain (host: $(hostname -s))"
fi
echo ""

BRAIN_PLIST="${HOME}/Library/LaunchAgents/com.jarvis.alpha.brain.plist"
if [ -f "$BRAIN_PLIST" ]; then
  echo ""
  echo "Restarting Alpha Brain LaunchAgent..."
  launchctl unload "$BRAIN_PLIST" 2>/dev/null || true
  sleep 1
  lsof -ti :8186 | xargs kill -9 2>/dev/null || true
  sleep 2
  find "${REPO_DIR}/brain" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
  launchctl load "$BRAIN_PLIST"
  sleep 4
  if curl -sk --max-time 5 https://jarvis-brain.tail40ed36.ts.net:8186/health | grep -q '"status":"ok"'; then
    echo "✅ Alpha Brain healthy after restart"
  else
    echo "⚠️  Alpha Brain health check failed — check logs"
    tail -5 "${REPO_DIR}/logs/alpha_brain_error.log" 2>/dev/null
  fi

  echo ""
  echo "Restarting Buddy Agent..."
  launchctl unload ~/Library/LaunchAgents/com.jarvis.alpha.buddy.plist 2>/dev/null
  sleep 1
  launchctl load ~/Library/LaunchAgents/com.jarvis.alpha.buddy.plist
  echo "✅ Buddy agent restarted"

  echo ""
  echo "── TEST GATE ────────────────────────────────────────────"
  VENV_PY="${REPO_DIR}/.venv/bin/python"
  if [ ! -x "$VENV_PY" ]; then
    echo "⚠️  No venv at $VENV_PY — skipping tests"
  elif [ ! -d "${REPO_DIR}/tests" ]; then
    echo "ℹ️  No tests/ directory — skipping"
  else
    cd "$REPO_DIR"
    PYTEST_LOG=$(mktemp)
    if "$VENV_PY" -m pytest tests/ -q --tb=short --no-header >"$PYTEST_LOG" 2>&1; then
      PASS_LINE=$(grep -E "[0-9]+ passed" "$PYTEST_LOG" | tail -1)
      echo "✅ Tests passed — $PASS_LINE"
      rm -f "$PYTEST_LOG"
    else
      echo "❌ TESTS FAILED — details:"
      echo "─────────────────────────────────────────────────────────"
      cat "$PYTEST_LOG"
      echo "─────────────────────────────────────────────────────────"
      rm -f "$PYTEST_LOG"
      echo ""
      echo "⚠️  Services ARE running ($NEW_HEAD deployed). Tests flagged issues."
      echo "   Fix tests before next deploy or revert commit."
      exit 1
    fi
  fi
  echo "─────────────────────────────────────────────────────────"
fi
