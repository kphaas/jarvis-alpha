#!/usr/bin/env bash
set -a
source ~/jarvis/.secrets
set +a

cd ~/jarvis-alpha
export PYTHONPATH="$(pwd)/common${PYTHONPATH:+:$PYTHONPATH}"
exec .venv/bin/python3.12 -m brain.agents.watchdog_agent \
  >> ~/jarvis-alpha/logs/alpha_watchdog.log 2>> ~/jarvis-alpha/logs/alpha_watchdog_error.log
