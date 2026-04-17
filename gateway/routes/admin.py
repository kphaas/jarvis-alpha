"""Gateway admin routes — key rotation with atomic file write and rollback."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import stat
import subprocess
import tempfile
import uuid

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from jarvis_common.logging_config import get_logger
from jarvis_common.secrets import clear_cache, get_secret

logger = get_logger("alpha_gateway")
admin_router = APIRouter(prefix="/v1/admin", tags=["admin"])

_rotation_lock = asyncio.Lock()

SECRETS_FILE = os.getenv("SECRETS_FILE", os.path.expanduser("~/jarvis/.secrets"))

KEY_FORMAT_RULES: dict[str, dict] = {
    "ANTHROPIC_API_KEY": {"prefix": "sk-ant-", "min_length": 40},
    "GEMINI_API_KEY": {"prefix": "AIza", "min_length": 30},
    "PERPLEXITY_API_KEY": {"prefix": "pplx-", "min_length": 40},
}

PROVIDER_TEST_URLS: dict[str, dict] = {
    "ANTHROPIC_API_KEY": {
        "url": "https://api.anthropic.com/v1/messages",
        "headers_fn": "anthropic",
        "test_body": {
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 10,
            "messages": [{"role": "user", "content": "ping"}],
        },
    },
    "GEMINI_API_KEY": {
        "url_fn": "gemini",
        "test_body": {
            "contents": [{"parts": [{"text": "ping"}]}],
            "generationConfig": {"maxOutputTokens": 10},
        },
    },
    "PERPLEXITY_API_KEY": {
        "url": "https://api.perplexity.ai/chat/completions",
        "headers_fn": "bearer",
        "test_body": {
            "model": "sonar",
            "max_tokens": 10,
            "messages": [{"role": "user", "content": "ping"}],
        },
    },
}


class RotateKeyRequest(BaseModel):
    key_name: str
    new_value: str
    rotation_id: str = Field(default_factory=lambda: uuid.uuid4().hex)


class RotateKeyResponse(BaseModel):
    status: str
    rotation_id: str
    key_name: str
    error: str | None = None
    old_key_health: str | None = None
    new_key_health: str | None = None


def _validate_key_format(key_name: str, value: str) -> str | None:
    """Validate key format. Returns error string or None if valid."""
    rule = KEY_FORMAT_RULES.get(key_name)
    if not rule:
        return None
    if rule.get("prefix") and not value.startswith(rule["prefix"]):
        return f"Key must start with '{rule['prefix']}'"
    if rule.get("min_length") and len(value) < rule["min_length"]:
        return f"Key must be at least {rule['min_length']} characters"
    if not value.isascii():
        return "Key must be ASCII only"
    return None


def _read_secrets_file() -> list[str]:
    """Read the secrets file as lines."""
    with open(SECRETS_FILE) as f:
        return f.readlines()


def _write_secrets_atomic(lines: list[str]) -> None:
    """Write secrets file atomically via temp file + os.replace."""
    dir_path = os.path.dirname(SECRETS_FILE) or "."
    fd, tmp_path = tempfile.mkstemp(dir=dir_path, prefix=".secrets_tmp_")
    try:
        os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "w") as f:
            f.writelines(lines)
        os.replace(tmp_path, SECRETS_FILE)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _backup_secrets() -> str:
    """Create a .bak copy of the secrets file. Returns backup path."""
    bak_path = SECRETS_FILE + ".bak"
    shutil.copy2(SECRETS_FILE, bak_path)
    os.chmod(bak_path, stat.S_IRUSR | stat.S_IWUSR)
    return bak_path


def _restore_from_backup(bak_path: str) -> None:
    """Restore secrets file from backup atomically."""
    os.replace(bak_path, SECRETS_FILE)


def _update_key_in_lines(lines: list[str], key_name: str, new_value: str) -> list[str]:
    """Replace the value of key_name in secrets file lines. Adds if not found."""
    updated = False
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            new_lines.append(line)
            continue
        k, _ = stripped.split("=", 1)
        if k.strip() == key_name:
            new_lines.append(f"{key_name}={new_value}\n")
            updated = True
        else:
            new_lines.append(line)
    if not updated:
        new_lines.append(f"{key_name}={new_value}\n")
    return new_lines


async def _test_key(key_name: str, api_key: str) -> tuple[bool, str]:
    """Test an API key by making a minimal request to the provider. Returns (success, detail)."""
    config = PROVIDER_TEST_URLS.get(key_name)
    if not config:
        return True, "no test configured"

    if config.get("headers_fn") == "anthropic":
        headers = [
            "-H",
            f"x-api-key: {api_key}",
            "-H",
            "anthropic-version: 2023-06-01",
            "-H",
            "content-type: application/json",
        ]
        url = config["url"]
    elif config.get("headers_fn") == "bearer":
        headers = [
            "-H",
            f"Authorization: Bearer {api_key}",
            "-H",
            "content-type: application/json",
        ]
        url = config["url"]
    elif config.get("url_fn") == "gemini":
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
        headers = ["-H", "content-type: application/json"]
    else:
        return True, "no test configured"

    cmd = [
        "curl",
        "-sk",
        "--max-time",
        "15",
        "-o",
        "/dev/null",
        "-w",
        "%{http_code}",
        "-X",
        "POST",
        url,
        *headers,
        "-d",
        json.dumps(config["test_body"]),
    ]

    try:
        result = await asyncio.to_thread(
            subprocess.run, cmd, capture_output=True, text=True, timeout=20
        )
        status_code = result.stdout.strip()
        if status_code.startswith("2"):
            return True, f"HTTP {status_code}"
        if status_code in ("401", "403"):
            return False, f"HTTP {status_code} — authentication failed"
        return False, f"HTTP {status_code}"
    except Exception as e:
        return False, str(e)


@admin_router.post("/rotate-key", response_model=RotateKeyResponse)
async def rotate_key(
    req: RotateKeyRequest,
    authorization: str = Header(...),
):
    expected_token = get_secret("GATEWAY_TOKEN")
    if not authorization.startswith("Bearer ") or authorization[7:] != expected_token:
        raise HTTPException(status_code=403, detail="Invalid admin token")

    allowed_keys = set(KEY_FORMAT_RULES.keys())
    if req.key_name not in allowed_keys:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot rotate '{req.key_name}'. Allowed: {sorted(allowed_keys)}",
        )

    fmt_error = _validate_key_format(req.key_name, req.new_value)
    if fmt_error:
        raise HTTPException(
            status_code=400, detail=f"Format validation failed: {fmt_error}"
        )

    if _rotation_lock.locked():
        raise HTTPException(status_code=409, detail="Another rotation is in progress")

    async with _rotation_lock:
        logger.info(
            "rotation_start key=%s rotation_id=%s", req.key_name, req.rotation_id
        )

        old_value = None
        bak_path = None
        try:
            try:
                old_value = get_secret(req.key_name)
            except KeyError:
                old_value = None

            old_healthy, old_detail = False, "no old key"
            if old_value:
                old_healthy, old_detail = await _test_key(req.key_name, old_value)
            logger.info("rotation old_key_health=%s detail=%s", old_healthy, old_detail)

            bak_path = _backup_secrets()
            logger.info("rotation backup=%s", bak_path)

            lines = _read_secrets_file()
            new_lines = _update_key_in_lines(lines, req.key_name, req.new_value)
            _write_secrets_atomic(new_lines)
            logger.info("rotation file_written key=%s", req.key_name)

            os.environ[req.key_name] = req.new_value
            clear_cache(req.key_name)
            logger.info("rotation env_updated cache_cleared key=%s", req.key_name)

            await asyncio.sleep(5)

            new_healthy, new_detail = await _test_key(req.key_name, req.new_value)
            logger.info("rotation new_key_health=%s detail=%s", new_healthy, new_detail)

            if new_healthy:
                if bak_path and os.path.exists(bak_path):
                    os.unlink(bak_path)
                logger.info(
                    "rotation_success key=%s rotation_id=%s",
                    req.key_name,
                    req.rotation_id,
                )
                return RotateKeyResponse(
                    status="success",
                    rotation_id=req.rotation_id,
                    key_name=req.key_name,
                    old_key_health=old_detail,
                    new_key_health=new_detail,
                )
            logger.warning(
                "rotation_rollback key=%s reason=%s", req.key_name, new_detail
            )
            if bak_path and os.path.exists(bak_path):
                _restore_from_backup(bak_path)
            if old_value:
                os.environ[req.key_name] = old_value
            clear_cache(req.key_name)
            return RotateKeyResponse(
                status="rolled_back",
                rotation_id=req.rotation_id,
                key_name=req.key_name,
                old_key_health=old_detail,
                new_key_health=new_detail,
                error=f"New key test failed: {new_detail}",
            )
        except Exception as e:
            logger.error("rotation_error key=%s error=%s", req.key_name, e)
            if bak_path and os.path.exists(bak_path):
                try:
                    _restore_from_backup(bak_path)
                    if old_value:
                        os.environ[req.key_name] = old_value
                    clear_cache(req.key_name)
                    logger.info("rotation emergency_rollback key=%s", req.key_name)
                except Exception as re:
                    logger.error(
                        "rotation rollback_also_failed key=%s error=%s",
                        req.key_name,
                        re,
                    )
            raise HTTPException(status_code=500, detail=f"Rotation failed: {e}")
