#!/usr/bin/env bash
set -a
source ~/jarvis/.secrets
set +a

cd ~/jarvis-alpha
export PYTHONPATH="$(pwd)/common${PYTHONPATH:+:$PYTHONPATH}"
exec .venv/bin/python3.12 -m brain.tasks.executor \
  >> ~/jarvis-alpha/logs/alpha_executor.log 2>> ~/jarvis-alpha/logs/alpha_executor_error.log
