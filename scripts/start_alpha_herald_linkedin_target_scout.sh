#!/usr/bin/env bash
set -a
source ~/jarvis/.secrets
set +a

cd ~/jarvis-alpha
export PYTHONPATH="$(pwd)/common${PYTHONPATH:+:$PYTHONPATH}"
exec .venv/bin/python3.12 -m brain.agents.herald_linkedin_target_scout \
  --trigger scheduled \
  >> ~/jarvis-alpha/logs/alpha_herald_linkedin_target_scout.log 2>> ~/jarvis-alpha/logs/alpha_herald_linkedin_target_scout_error.log
