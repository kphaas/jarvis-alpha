#!/usr/bin/env python3
"""
Generate a signed service JWT for node-to-node authentication.

Usage:
    python3 gen_service_token.py --iss gateway --actor-type service --scopes "dream.execute,cloud.call"
    python3 gen_service_token.py --iss buddy --actor-type agent --scopes "memory.evict,memory.promote,tasks.scan"
    python3 gen_service_token.py --iss sandbox --actor-type service --scopes "forge.deploy.submit,forge.costs.report"

The script looks for the private key at:
    ~/jarvis/pki/services/{iss}_private.pem   (Brain, Gateway, Endpoint)
    ~/pki/services/{iss}_private.pem           (Sandbox fallback)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

try:
    import jwt as pyjwt
except ImportError:
    print("FATAL: PyJWT not installed. Run: pip install PyJWT", file=sys.stderr)
    sys.exit(1)

from service_identity import DEFAULT_SCOPES, TOKEN_LIFETIME_DAYS, VALID_ISS_ACTOR_PAIRS


def find_private_key(iss: str) -> Path:
    """Look for private key in standard locations."""
    candidates = [
        Path.home() / "jarvis" / "pki" / "services" / f"{iss}_private.pem",
        Path.home() / "pki" / "services" / f"{iss}_private.pem",
    ]
    for path in candidates:
        if path.exists():
            return path
    print(f"FATAL: No private key found for '{iss}'. Searched:", file=sys.stderr)
    for c in candidates:
        print(f"  {c}", file=sys.stderr)
    sys.exit(1)


def generate_token(iss: str, actor_type: str, scopes: list[str], days: int = 7) -> str:
    """Generate and sign a service JWT."""
    if VALID_ISS_ACTOR_PAIRS.get(iss) != actor_type:
        print(f"WARNING: ({iss}, {actor_type}) not in VALID_ISS_ACTOR_PAIRS", file=sys.stderr)

    key_path = find_private_key(iss)
    private_key = key_path.read_text()

    now = int(time.time())
    payload = {
        "sub": iss,
        "iss": iss,
        "actor_type": actor_type,
        "scopes": scopes,
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + (days * 86400),
    }

    token = pyjwt.encode(payload, private_key, algorithm="RS256")
    return token


def main():
    parser = argparse.ArgumentParser(description="Generate a JARVIS service JWT")
    parser.add_argument("--iss", required=True, help="Issuer name (gateway, sandbox, buddy, endpoint)")
    parser.add_argument("--actor-type", default=None, help="Actor type (service or agent). Auto-detected if omitted.")
    parser.add_argument("--scopes", default=None, help="Comma-separated scopes. Uses defaults if omitted.")
    parser.add_argument("--days", type=int, default=TOKEN_LIFETIME_DAYS, help="Token lifetime in days (default: 7)")
    parser.add_argument("--json", action="store_true", help="Output full token details as JSON")
    args = parser.parse_args()

    iss = args.iss.lower()

    # Auto-detect actor type
    if args.actor_type:
        actor_type = args.actor_type
    elif iss == "buddy":
        actor_type = "agent"
    else:
        actor_type = "service"

    # Resolve scopes
    if args.scopes:
        scopes = [s.strip() for s in args.scopes.split(",")]
    else:
        scopes = list(DEFAULT_SCOPES.get(iss, ["health.read"]))
        if iss == "sandbox":
            for extra in ("forge.briefings.ingest", "briefings.read"):
                if extra not in scopes:
                    scopes.append(extra)

    token = generate_token(iss, actor_type, scopes, days=args.days)

    if args.json:
        # Decode without verification to show claims
        claims = pyjwt.decode(token, options={"verify_signature": False})
        output = {
            "token": token,
            "claims": claims,
            "key_path": str(find_private_key(iss)),
            "expires_in_days": args.days,
        }
        print(json.dumps(output, indent=2))
    else:
        print(token)


if __name__ == "__main__":
    main()
