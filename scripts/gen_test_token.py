#!/usr/bin/env python3
"""
Generate a short-lived RS256 admin JWT for alpha API testing.
Run from Brain: python3 ~/jarvis-alpha/scripts/gen_test_token.py
"""
import sys
import os

import jwt

def _load_private_key() -> bytes:
    path = None
    secrets = os.path.expanduser("~/jarvis/.secrets")
    with open(secrets) as f:
        for line in f:
            if line.startswith("JARVIS_JWT_PRIVATE_KEY_PATH="):
                path = line.strip().split("=", 1)[1]
                break
    if not path:
        raise RuntimeError("JARVIS_JWT_PRIVATE_KEY_PATH not found in ~/.jarvis/.secrets")
    with open(path, "rb") as f:
        return f.read()

from datetime import datetime, timedelta, timezone
now = datetime.now(timezone.utc)
payload = {
    "sub": "ken",
    "role": "admin",
    "iat": now,
    "exp": now + timedelta(hours=1),
}

token = jwt.encode(payload, _load_private_key(), algorithm="RS256")
print(token)
