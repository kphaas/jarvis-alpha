#!/usr/bin/env bash
set -a
source ~/jarvis/.secrets
set +a

cd ~/jarvis-alpha
export PYTHONPATH="$(pwd)/common${PYTHONPATH:+:$PYTHONPATH}"
exec .venv/bin/python3.12 scripts/run_market_brief.py \
  >> ~/jarvis-alpha/logs/alpha_market_brief.log \
  2>> ~/jarvis-alpha/logs/alpha_market_brief_error.log
