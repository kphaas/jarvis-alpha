#!/usr/bin/env bash
# Compatibility wrapper for legacy com.jarvis.certrenew jobs.
# New ownership lives with Sweep via sweep_tls_cert_renewal.py.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
THRESHOLD_DAYS="${DAYS_THRESHOLD:-30}"

exec python3 "${SCRIPT_DIR}/sweep_tls_cert_renewal.py" \
  --local \
  --threshold-days "${THRESHOLD_DAYS}" \
  --skip-registry
