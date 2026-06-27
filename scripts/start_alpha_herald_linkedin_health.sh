#!/usr/bin/env bash
set -a
source ~/jarvis/.secrets
set +a

cd ~/jarvis-alpha
export PYTHONPATH="$(pwd)/common${PYTHONPATH:+:$PYTHONPATH}"
exec .venv/bin/python3.12 -m brain.agents.herald_linkedin_health_watcher \
  --trigger scheduled \
  >> ~/jarvis-alpha/logs/alpha_herald_linkedin_health.log 2>> ~/jarvis-alpha/logs/alpha_herald_linkedin_health_error.log
