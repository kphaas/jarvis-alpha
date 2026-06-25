#!/usr/bin/env bash
set -a
source ~/jarvis/.secrets
set +a

cd ~/jarvis-alpha
export PYTHONPATH="$(pwd)/common${PYTHONPATH:+:$PYTHONPATH}"
exec .venv/bin/python3.12 scripts/run_ai_news_brief.py \
  >> ~/jarvis-alpha/logs/alpha_ai_news_brief.log \
  2>> ~/jarvis-alpha/logs/alpha_ai_news_brief_error.log
