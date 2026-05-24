#!/usr/bin/env bash
set -a
source ~/jarvis/.secrets
set +a

cd ~/jarvis-alpha
export PYTHONPATH="$(pwd)/common${PYTHONPATH:+:$PYTHONPATH}"
exec .venv/bin/python3.12 -m brain.agents.school_email_watcher \
  --trigger nightly \
  --max-results "${ALPHA_SCHOOL_EMAIL_MAX_RESULTS:-25}" \
  >> ~/jarvis-alpha/logs/alpha_school_email.log 2>> ~/jarvis-alpha/logs/alpha_school_email_error.log
