"""Secret loader with pluggable audit hooks.

Nodes register audit callbacks at startup. Brain registers a Postgres writer.
Gateway/Forge get stdout-only logging (no Postgres dependency in jarvis_common).
"""

import os
from datetime import datetime, timezone
from typing import Callable

from jarvis_common.logging_config import get_logger

logger = get_logger("jarvis_common")
SECRETS_FILE = os.getenv("SECRETS_FILE", os.path.expanduser("~/.secrets"))

_cache: dict[str, str] = {}
_audit_hooks: list[Callable[[str, str, str], None]] = []


def register_audit_hook(hook: Callable[[str, str, str], None]) -> None:
    """Register an audit callback: hook(key, source, timestamp_iso).

    Hooks are called synchronously after each secret access.
    If a hook raises, the error is logged but does not block secret retrieval.
    """
    _audit_hooks.append(hook)


def get_secret(key: str) -> str:
    if key in _cache:
        return _cache[key]
    val = os.getenv(key)
    if val:
        _cache[key] = val
        _emit_access(key, source="env")
        return val
    try:
        with open(SECRETS_FILE) as f:
            for line in f:
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.strip() == key:
                    _cache[key] = v.strip()
                    _emit_access(key, source="file")
                    return _cache[key]
    except FileNotFoundError:
        logger.error("Secrets file not found: %s", SECRETS_FILE)
    raise KeyError(f"Secret not found: {key}")


def clear_cache(key: str | None = None) -> None:
    """Clear one or all cached secrets. Used during key rotation."""
    if key:
        _cache.pop(key, None)
    else:
        _cache.clear()


def _emit_access(key: str, source: str) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    logger.info("secret_access key=%s source=%s at=%s", key, source, ts)
    for hook in _audit_hooks:
        try:
            hook(key, source, ts)
        except Exception as e:
            logger.warning("audit_hook failed: %s", e)
