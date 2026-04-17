#!/usr/bin/env python3
"""
Generate a short-lived RS256 admin JWT for jarvis-alpha API testing.

Usage:
    python3 ~/jarvis-alpha/scripts/gen_test_token.py
    python3 ~/jarvis-alpha/scripts/gen_test_token.py ryleigh

The token mirrors the claims structure issued by /v1/auth/pin so that
test tokens are functionally identical to real PIN-auth tokens.
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

import jwt

DEFAULT_PROFILE = "ken"

# Profile metadata mirrors alpha_profiles rows. Update if alpha_profiles changes.
PROFILES = {
    "ken": {
        "display_name": "Ken",
        "role": "admin",
        "max_rating": "adult",
        "child_age": None,
        "scopes": ["*"],
    },
    "ryleigh": {
        "display_name": "Ryleigh",
        "role": "child",
        "max_rating": "age_8_plus",
        "child_age": 8,
        "scopes": ["ask", "chat.read", "health.read"],
    },
    "sloane": {
        "display_name": "Sloane",
        "role": "child",
        "max_rating": "all_ages",
        "child_age": 5,
        "scopes": ["ask", "chat.read", "health.read"],
    },
}

DEFAULT_WORKSPACE = "personal"


def _load_private_key() -> bytes:
    secrets_path = os.path.expanduser("~/jarvis/.secrets")
    key_path = None
    with open(secrets_path) as f:
        for line in f:
            if line.startswith("JARVIS_JWT_PRIVATE_KEY_PATH="):
                key_path = line.strip().split("=", 1)[1]
                break
    if not key_path:
        # Fallback to the default location
        key_path = os.path.expanduser("~/jarvis/pki/jwt/jwt_private.pem")
    with open(key_path, "rb") as f:
        return f.read()


def main() -> None:
    profile_id = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PROFILE
    if profile_id not in PROFILES:
        print(f"Unknown profile: {profile_id}", file=sys.stderr)
        print(f"Valid profiles: {list(PROFILES.keys())}", file=sys.stderr)
        sys.exit(1)

    p = PROFILES[profile_id]
    now = datetime.now(timezone.utc)

    claims = {
        "sub": profile_id,
        "iss": "user",
        "role": p["role"],
        "profile_id": profile_id,
        "workspace_id": DEFAULT_WORKSPACE,
        "display_name": p["display_name"],
        "actor_type": "user",
        "max_rating": p["max_rating"],
        "scopes": p["scopes"],
        "jti": str(uuid.uuid4()),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=1)).timestamp()),
    }
    if p["child_age"] is not None:
        claims["child_age"] = p["child_age"]

    token = jwt.encode(claims, _load_private_key(), algorithm="RS256")
    print(token)


if __name__ == "__main__":
    main()
