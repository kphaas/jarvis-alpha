#!/usr/bin/env bash
set -a
source ~/jarvis/.secrets
set +a

cd ~/jarvis-alpha
export PYTHONPATH="$(pwd)/common${PYTHONPATH:+:$PYTHONPATH}"
exec .venv/bin/python3.12 -m brain.agents.gmail_oauth_health_watcher \
  --trigger scheduled \
  >> ~/jarvis-alpha/logs/alpha_gmail_health.log 2>> ~/jarvis-alpha/logs/alpha_gmail_health_error.log
