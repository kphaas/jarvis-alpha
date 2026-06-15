#!/usr/bin/env bash
set -a
source ~/jarvis/.secrets
set +a

cd ~/jarvis-alpha
export PYTHONPATH="$(pwd)/common${PYTHONPATH:+:$PYTHONPATH}"
exec .venv/bin/python3.12 scripts/run_beacon_quality_canary.py \
  >> ~/jarvis-alpha/logs/alpha_beacon_quality_canary.log \
  2>> ~/jarvis-alpha/logs/alpha_beacon_quality_canary_error.log
