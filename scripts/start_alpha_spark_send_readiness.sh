#!/usr/bin/env bash
set -euo pipefail

if [ -f ~/jarvis/.secrets ]; then
  set -a
  # shellcheck disable=SC1090
  source ~/jarvis/.secrets
  set +a
fi

cd ~/jarvis-alpha
mkdir -p logs
exec bash scripts/smoke_spark_send_readiness.sh \
  >> ~/jarvis-alpha/logs/alpha_spark_send_readiness.log \
  2>> ~/jarvis-alpha/logs/alpha_spark_send_readiness_error.log
