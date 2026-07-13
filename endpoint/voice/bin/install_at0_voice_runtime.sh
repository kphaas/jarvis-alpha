#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${JARVIS_ALPHA_REPO_DIR:-${HOME}/jarvis-alpha}"
VOICE_DIR="${REPO_DIR}/endpoint/voice"
PYTHON_BIN="${PYTHON_BIN:-python3.12}"
MODEL_REPO="${JARVIS_AT0_VOICE_MODEL_REPO:-Systran/faster-whisper-base.en}"
MODEL_REVISION="${JARVIS_AT0_VOICE_MODEL_REVISION:-3d3d5dee26484f91867d81cb899cfcf72b96be6c}"
MODEL_PATH="${JARVIS_AT0_VOICE_MODEL_PATH:-${VOICE_DIR}/models/faster-whisper-base.en}"
MODEL_PATH="${MODEL_PATH/#\~/${HOME}}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  PYTHON_BIN="python3"
fi

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "AT-0 voice install failed: python not found" >&2
  exit 1
fi

mkdir -p "${VOICE_DIR}/logs" "${VOICE_DIR}/models"

if [ ! -d "${VOICE_DIR}/.venv" ]; then
  "$PYTHON_BIN" -m venv "${VOICE_DIR}/.venv"
fi

"${VOICE_DIR}/.venv/bin/python" -m pip install --upgrade pip >/dev/null
"${VOICE_DIR}/.venv/bin/python" -m pip install -r "${VOICE_DIR}/requirements.txt"
"${VOICE_DIR}/.venv/bin/python" -m compileall -q "${VOICE_DIR}/at0_voice_service.py"

if [ ! -s "${MODEL_PATH}/model.bin" ]; then
  "${VOICE_DIR}/.venv/bin/hf" download "${MODEL_REPO}" \
    --revision "${MODEL_REVISION}" \
    --local-dir "${MODEL_PATH}" \
    --quiet
fi

test -s "${MODEL_PATH}/config.json"
test -s "${MODEL_PATH}/model.bin"

cat <<MSG
AT-0 voice runtime installed.
Model path defaults to:
  ${MODEL_PATH}
Override with JARVIS_AT0_VOICE_MODEL_PATH if needed.
MSG
