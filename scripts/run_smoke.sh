#!/bin/bash
# run_smoke.sh — Slab 5.5 RLS smoke harness wrapper
#
# Purpose: prepare the non-owner smoke role, seed fixtures, and run
#          the RLS smoke harness against jarvis_alpha_test. Refuses to
#          run against any other database.
#
# Usage:
#   bash scripts/run_smoke.sh test
#
# Notes:
#   - The "test" argument is required and is the ONLY accepted target.
#     Anything else (prod, alpha, etc.) is rejected — defense against
#     accidentally smoking against production.
#   - Ken creates the jarvis_alpha_test database manually
#     (CREATE DATABASE jarvis_alpha_test) before running this script;
#     this wrapper does NOT create or drop databases.
#   - All output is tee'd to /tmp/rls_smoke_<timestamp>.log so the run
#     is reviewable after the fact.
#
# Round 2 (2026-05-01): the harness now runs as a non-owner role
# (jarvis_alpha_smoke) so RLS is actually enforced. Owner roles bypass
# RLS by default, which was causing Case 1 to falsely pass. Steps 1 + 2
# still run as jarvisbrain (the owner) because they need DDL/seed
# privileges; only step 3 (the smoke harness itself) runs as the
# non-owner.

set -uo pipefail

# ── Config ────────────────────────────────────────────────
PSQL_PATH="/opt/homebrew/Cellar/postgresql@16/16.13/bin/psql"
DB_NAME="jarvis_alpha_test"

# Owner role used to create the smoke role and seed fixtures.
OWNER_ROLE="jarvisbrain"
# Non-owner role used to actually run the smoke harness so that RLS
# policies are enforced (table owners bypass RLS by default).
SMOKE_ROLE="jarvis_alpha_smoke"

# Resolve repo root from this script's location so the wrapper works
# regardless of pwd.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ROLE_SQL="${REPO_ROOT}/brain/db/tests/test_role_setup.sql"
SETUP_SQL="${REPO_ROOT}/brain/db/tests/test_data_setup.sql"
SMOKE_SQL="${REPO_ROOT}/brain/db/tests/rls_smoke.sql"

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="/tmp/rls_smoke_${TIMESTAMP}.log"

# ── Colors ────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

usage() {
    cat <<EOF
Usage: $(basename "$0") test

Required argument:
  test    The ONLY accepted value. Targets database '${DB_NAME}'.
          Any other value is rejected.

Example:
  bash scripts/run_smoke.sh test

Output:
  Logs are written to /tmp/rls_smoke_<timestamp>.log

Files executed (in order):
  1. ${ROLE_SQL}             (as ${OWNER_ROLE})
  2. ${SETUP_SQL}             (as ${OWNER_ROLE})
  3. ${SMOKE_SQL}             (as ${SMOKE_ROLE})
EOF
}

# ── Argument validation ───────────────────────────────────
if [ "$#" -ne 1 ]; then
    echo -e "${RED}ERROR: exactly 1 argument required${NC}" >&2
    usage >&2
    exit 2
fi

if [ "$1" != "test" ]; then
    echo -e "${RED}ERROR: refusing to run against target '$1'${NC}" >&2
    echo -e "${RED}       only 'test' is accepted (db=${DB_NAME}).${NC}" >&2
    echo -e "${RED}       This is a guardrail against accidental prod smoke.${NC}" >&2
    exit 2
fi

# ── psql binary verification ──────────────────────────────
if [ ! -x "${PSQL_PATH}" ]; then
    echo -e "${RED}ERROR: psql not found at ${PSQL_PATH}${NC}" >&2
    echo -e "${RED}       Install or fix PSQL_PATH at top of this script.${NC}" >&2
    exit 3
fi

# ── Fixture file existence ────────────────────────────────
if [ ! -f "${ROLE_SQL}" ]; then
    echo -e "${RED}ERROR: role setup script missing: ${ROLE_SQL}${NC}" >&2
    exit 4
fi

if [ ! -f "${SETUP_SQL}" ]; then
    echo -e "${RED}ERROR: setup script missing: ${SETUP_SQL}${NC}" >&2
    exit 4
fi

if [ ! -f "${SMOKE_SQL}" ]; then
    echo -e "${RED}ERROR: smoke script missing: ${SMOKE_SQL}${NC}" >&2
    exit 4
fi

# ── Banner ────────────────────────────────────────────────
{
    echo "============================================================"
    echo "RLS smoke harness — $(date)"
    echo "  database:    ${DB_NAME}"
    echo "  psql:        ${PSQL_PATH}"
    echo "  owner role:  ${OWNER_ROLE}  (steps 1 + 2)"
    echo "  smoke role:  ${SMOKE_ROLE}  (step 3, NOBYPASSRLS)"
    echo "  role setup:  ${ROLE_SQL}"
    echo "  data setup:  ${SETUP_SQL}"
    echo "  smoke:       ${SMOKE_SQL}"
    echo "  log:         ${LOG_FILE}"
    echo "============================================================"
} | tee "${LOG_FILE}"

# ── Step 1: ensure non-owner smoke role exists ────────────
echo -e "${YELLOW}[1/3] applying test_role_setup.sql as ${OWNER_ROLE}...${NC}" | tee -a "${LOG_FILE}"
"${PSQL_PATH}" \
    -d "${DB_NAME}" \
    -U "${OWNER_ROLE}" \
    -v ON_ERROR_STOP=1 \
    -f "${ROLE_SQL}" 2>&1 | tee -a "${LOG_FILE}"
ROLE_RC="${PIPESTATUS[0]}"

if [ "${ROLE_RC}" -ne 0 ]; then
    echo -e "${RED}FAIL: test_role_setup.sql exited ${ROLE_RC}${NC}" | tee -a "${LOG_FILE}"
    echo -e "${RED}      log: ${LOG_FILE}${NC}"
    exit "${ROLE_RC}"
fi
echo -e "${GREEN}[1/3] role setup OK${NC}" | tee -a "${LOG_FILE}"

# ── Step 2: seed fixtures (as owner — needs INSERT privileges) ─
echo -e "${YELLOW}[2/3] applying test_data_setup.sql as ${OWNER_ROLE}...${NC}" | tee -a "${LOG_FILE}"
"${PSQL_PATH}" \
    -d "${DB_NAME}" \
    -U "${OWNER_ROLE}" \
    -v ON_ERROR_STOP=1 \
    -f "${SETUP_SQL}" 2>&1 | tee -a "${LOG_FILE}"
SETUP_RC="${PIPESTATUS[0]}"

if [ "${SETUP_RC}" -ne 0 ]; then
    echo -e "${RED}FAIL: test_data_setup.sql exited ${SETUP_RC}${NC}" | tee -a "${LOG_FILE}"
    echo -e "${RED}      log: ${LOG_FILE}${NC}"
    exit "${SETUP_RC}"
fi
echo -e "${GREEN}[2/3] data setup OK${NC}" | tee -a "${LOG_FILE}"

# ── Step 3: run smoke harness as the non-owner role ───────
echo -e "${YELLOW}[3/3] running rls_smoke.sql as ${SMOKE_ROLE} (RLS enforced)...${NC}" | tee -a "${LOG_FILE}"
"${PSQL_PATH}" \
    -d "${DB_NAME}" \
    -U "${SMOKE_ROLE}" \
    -v ON_ERROR_STOP=1 \
    -f "${SMOKE_SQL}" 2>&1 | tee -a "${LOG_FILE}"
SMOKE_RC="${PIPESTATUS[0]}"

if [ "${SMOKE_RC}" -ne 0 ]; then
    echo -e "${RED}FAIL: rls_smoke.sql exited ${SMOKE_RC}${NC}" | tee -a "${LOG_FILE}"
    echo -e "${RED}      log: ${LOG_FILE}${NC}"
    exit "${SMOKE_RC}"
fi

echo -e "${GREEN}[3/3] smoke OK — all 8 cases passed${NC}" | tee -a "${LOG_FILE}"
echo "log: ${LOG_FILE}"
exit 0
