import os
import logging
from datetime import datetime

logger = logging.getLogger(__name__)
SECRETS_FILE = os.getenv("SECRETS_FILE", os.path.expanduser("~/.secrets"))

_cache: dict = {}


def get_secret(key: str) -> str:
    if key in _cache:
        return _cache[key]
    val = os.getenv(key)
    if val:
        _cache[key] = val
        _log_access(key, source="env")
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
                    _log_access(key, source="file")
                    return _cache[key]
    except FileNotFoundError:
        logger.error(f"Secrets file not found: {SECRETS_FILE}")
    raise KeyError(f"Secret not found: {key}")


def _log_access(key: str, source: str):
    logger.info(
        f"secret_access key={key} source={source} at={datetime.utcnow().isoformat()}"
    )
