#!/usr/bin/env bash
set -a
source ~/jarvis/.secrets
set +a

cd ~/jarvis-alpha
export PYTHONPATH="$(pwd)/common${PYTHONPATH:+:$PYTHONPATH}"
exec .venv/bin/python3.12 -m brain.agents.at0_mail_watcher \
  --trigger scheduled \
  --max-results "${AT0_HERALD_MAX_RESULTS:-25}" \
  >> ~/jarvis-alpha/logs/alpha_at0_mail.log 2>> ~/jarvis-alpha/logs/alpha_at0_mail_error.log
