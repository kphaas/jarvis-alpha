#!/usr/bin/env python3
"""
Rotate RS256 service JWTs in node secrets files and verify connectivity.

Usage:
    python3 rotate_service_token.py --node brain
    python3 rotate_service_token.py --node gateway --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

try:
    import jwt as pyjwt
except ImportError:
    print(
        json.dumps(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "level": "error",
                "service": "token_rotation",
                "node": "unknown",
                "message": "PyJWT not installed. Run: pip install PyJWT",
            }
        ),
        file=sys.stderr,
    )
    sys.exit(1)

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from service_identity import DEFAULT_SCOPES, TOKEN_LIFETIME_DAYS, VALID_ISS_ACTOR_PAIRS  # noqa: E402

NODE_CONFIG = {
    "brain": {
        "iss": "buddy",
        "actor_type": "agent",
        "secret_key": "ALPHA_BUDDY_TOKEN",
        "private_key_path": "~/jarvis/pki/services/buddy_private.pem",
        "secrets_file": "~/jarvis/.secrets",
    },
    "brain_service": {
        "iss": "brain",
        "actor_type": "service",
        "secret_key": "ALPHA_BRAIN_SERVICE_TOKEN",
        "private_key_path": "~/jarvis/pki/services/brain_private.pem",
        "secrets_file": "~/jarvis/.secrets",
    },
    "gateway": {
        "iss": "gateway",
        "actor_type": "service",
        "secret_key": "ALPHA_SERVICE_TOKEN",
        "private_key_path": "~/jarvis/pki/services/gateway_private.pem",
        "secrets_file": "~/jarvis/.secrets",
    },
    "sandbox": {
        "iss": "sandbox",
        "actor_type": "service",
        "secret_key": "ALPHA_SERVICE_TOKEN",
        "private_key_path": "~/pki/services/sandbox_private.pem",
        "secrets_file": "~/.secrets",
    },
    "endpoint": {
        "iss": "endpoint",
        "actor_type": "service",
        "secret_key": "ALPHA_SERVICE_TOKEN",
        "private_key_path": "~/jarvis/pki/services/endpoint_private.pem",
        "secrets_file": "~/jarvis/.secrets",
    },
}

BRAIN_HEALTH_URL = "https://jarvis-brain.tail40ed36.ts.net:8186/health"
BUDDY_EVENTS_URL = "https://jarvis-brain.tail40ed36.ts.net:8186/v1/buddy/events"
PSQL_BIN = "/opt/homebrew/Cellar/postgresql@16/16.13/bin/psql"
PSQL_DB = "jarvis_alpha"
PSQL_HOST = "localhost"
PSQL_USER = "jarvisbrain"
CURL_TIMEOUT_SEC = "10"


def log_json(
    level: str,
    message: str,
    node: str,
    **extra: object,
) -> None:
    rec: dict[str, object] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "service": "token_rotation",
        "node": node,
        "message": message,
    }
    rec.update(extra)
    print(json.dumps(rec), flush=True)


def read_secret_value(secrets_file: str, secret_key: str) -> str | None:
    path = Path(secrets_file).expanduser()
    if not path.is_file():
        return None
    prefix = f"{secret_key}="
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    return None


def postgres_password(secrets_file: str) -> str:
    password = os.getenv("POSTGRES_PASSWORD", "").strip()
    if password:
        return password
    password = (read_secret_value(secrets_file, "POSTGRES_PASSWORD") or "").strip()
    if password:
        return password
    raise RuntimeError("POSTGRES_PASSWORD unavailable for local psql verification")


def run_brain_psql(sql: str, secrets_file: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PGPASSWORD"] = postgres_password(secrets_file)
    return subprocess.run(
        [
            PSQL_BIN,
            "-h",
            PSQL_HOST,
            "-d",
            PSQL_DB,
            "-U",
            PSQL_USER,
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            sql,
        ],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )


def days_remaining(secrets_file: str, secret_key: str) -> float | None:
    """Decode current token and return days until exp. None if missing or undecodable."""
    current = read_secret_value(secrets_file, secret_key)
    if not current:
        return None
    try:
        import base64

        payload_b64 = current.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        exp = payload.get("exp", 0)
        now = datetime.now(timezone.utc).timestamp()
        return (exp - now) / 86400.0
    except Exception:
        return None


def generate_token(
    iss: str,
    actor_type: str,
    private_key_path: str,
    scopes: list[str],
    days: int = TOKEN_LIFETIME_DAYS,
) -> str:
    key_path = Path(private_key_path).expanduser()
    if not key_path.is_file():
        raise FileNotFoundError(f"Private key not found: {key_path}")

    private_key = key_path.read_text(encoding="utf-8")
    now = int(time.time())
    payload = {
        "sub": f"{iss}_service",
        "iss": iss,
        "actor_type": actor_type,
        "scopes": scopes,
        "iat": now,
        "exp": now + (days * 86400),
        "jti": str(uuid.uuid4()),
    }
    token = pyjwt.encode(payload, private_key, algorithm="RS256")
    if isinstance(token, bytes):
        token = token.decode("ascii")
    return token


def atomic_update_secrets(secrets_file: str, secret_key: str, new_value: str) -> None:
    secrets_path = Path(secrets_file).expanduser()
    parent = secrets_path.parent
    parent.mkdir(parents=True, exist_ok=True)

    if secrets_path.exists():
        content = secrets_path.read_text(encoding="utf-8")
        mode = secrets_path.stat().st_mode & 0o777
    else:
        content = ""
        mode = 0o600

    prefix = f"{secret_key}="
    new_line = f"{secret_key}={new_value}\n"
    lines = content.splitlines(keepends=True)
    out: list[str] = []
    found = False
    for line in lines:
        if line.startswith(prefix):
            out.append(new_line)
            found = True
        else:
            out.append(line)
    if not found:
        if out and not (out[-1].endswith("\n") or out[-1].endswith("\r\n")):
            out.append("\n")
        elif not out:
            pass
        out.append(new_line)

    text = "".join(out)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(parent),
        prefix=f".{secrets_path.name}.",
        suffix=".tmp",
        delete=False,
    ) as tf:
        tmp_name = tf.name
        tf.write(text)

    try:
        os.chmod(tmp_name, mode)
        os.rename(tmp_name, str(secrets_path))
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def alert_failure(
    node: str,
    error_msg: str,
    old_token: str | None,
    secrets_file: str,
) -> None:
    """Best-effort alert; failures here are logged but do not change exit code."""
    payload_obj = {"node": node, "error": error_msg}
    if node == "brain":
        payload_json = json.dumps(payload_obj)
        escaped = payload_json.replace("'", "''")
        sql = (
            "INSERT INTO alpha_buddy_events (event_type, source, payload, created_at) "
            f"VALUES ('alert', 'token_rotation', '{escaped}', NOW());"
        )
        try:
            result = run_brain_psql(sql, secrets_file)
            if result.returncode != 0:
                err = (result.stderr or result.stdout or "").strip()
                raise RuntimeError(err or f"exit {result.returncode}")
        except Exception as exc:
            log_json(
                "error",
                f"alert_failure psql failed: {exc}",
                node,
                alert_target="psql",
            )
        return

    if not old_token:
        log_json(
            "error",
            "alert_failure skipped: no old token available for curl",
            node,
        )
        return

    body = json.dumps(
        {
            "event_type": "alert",
            "source": "token_rotation",
            "payload": payload_obj,
        }
    )
    try:
        subprocess.run(
            [
                "curl",
                "-sk",
                "-X",
                "POST",
                BUDDY_EVENTS_URL,
                "-H",
                f"Authorization: Bearer {old_token}",
                "-H",
                "Content-Type: application/json",
                "-d",
                body,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception as exc:
        log_json(
            "error",
            f"alert_failure curl failed: {exc}",
            node,
            alert_target="buddy_events",
        )


def verify_brain(secrets_file: str) -> None:
    sql = "SELECT 1 FROM alpha_buddy_events LIMIT 1"
    r = run_brain_psql(sql, secrets_file)
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip() or f"exit {r.returncode}"
        raise RuntimeError(f"psql verification failed: {err}")


def verify_gateway_sandbox(token: str) -> None:
    r = subprocess.run(
        [
            "curl",
            "-sk",
            "--max-time",
            CURL_TIMEOUT_SEC,
            "-o",
            "/dev/null",
            "-w",
            "%{http_code}",
            "-H",
            f"Authorization: Bearer {token}",
            BRAIN_HEALTH_URL,
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if r.returncode != 0:
        raise RuntimeError(f"curl failed: {r.stderr or r.stdout or r.returncode}")
    code = (r.stdout or "").strip()
    if code != "200":
        raise RuntimeError(f"health check HTTP {code}, expected 200")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rotate JARVIS service JWT in secrets file"
    )
    parser.add_argument(
        "--node",
        required=True,
        choices=("brain", "brain_service", "gateway", "sandbox", "endpoint"),
        help="Target node",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show actions and generate token only; do not write or verify",
    )
    parser.add_argument(
        "--min-days-remaining",
        type=float,
        default=2.0,
        help="Skip rotation if current token has more than this many days remaining (default: 2.0)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rotate even if token still has more than min_days_remaining left",
    )
    args = parser.parse_args()

    node = args.node
    cfg = NODE_CONFIG[node]
    iss = cfg["iss"]
    actor_type = cfg["actor_type"]
    secret_key = cfg["secret_key"]
    secrets_file = cfg["secrets_file"]
    private_key_path = cfg["private_key_path"]

    scopes = DEFAULT_SCOPES.get(iss)
    if not scopes:
        log_json("error", f"No DEFAULT_SCOPES for iss={iss}", node)
        return 1

    resolved = {
        "node": node,
        "iss": iss,
        "actor_type": actor_type,
        "secret_key": secret_key,
        "min_days_remaining": args.min_days_remaining,
        "force": args.force,
        "secrets_file": str(Path(secrets_file).expanduser()),
        "private_key_path": str(Path(private_key_path).expanduser()),
        "private_key_exists": Path(private_key_path).expanduser().is_file(),
    }

    log_json("info", "rotation started", node)

    old_token: str | None = None
    if node in ("gateway", "sandbox"):
        old_token = read_secret_value(secrets_file, secret_key)

    try:
        if VALID_ISS_ACTOR_PAIRS.get(iss) != actor_type:
            log_json(
                "info",
                f"({iss}, {actor_type}) not in VALID_ISS_ACTOR_PAIRS (see SERVICE_IDENTITY_MODEL.md)",
                node,
            )

        if args.dry_run:
            log_json("info", "dry-run config", node, config=resolved)
            token = generate_token(iss, actor_type, private_key_path, scopes)
            log_json("info", "token generated (dry-run)", node, token_length=len(token))
            log_json(
                "info",
                f"would update {Path(secrets_file).expanduser()} key {secret_key}",
                node,
            )
            log_json("info", "rotation complete (dry-run)", node)
            return 0

        # Guard: skip if token is not near expiry
        if not args.dry_run and not args.force:
            remaining = days_remaining(secrets_file, secret_key)
            if remaining is not None and remaining > args.min_days_remaining:
                log_json(
                    "info",
                    "rotation skipped — token still valid",
                    node,
                    days_remaining=round(remaining, 2),
                    min_days_remaining=args.min_days_remaining,
                )
                return 0

        token = generate_token(iss, actor_type, private_key_path, scopes)
        log_json("info", "token generated", node, token_length=len(token))

        atomic_update_secrets(secrets_file, secret_key, token)
        log_json(
            "info",
            "secrets file updated",
            node,
            path=str(Path(secrets_file).expanduser()),
        )

        if node == "brain":
            verify_brain(secrets_file)
            log_json("info", "verification result: ok (psql)", node)
        else:
            verify_gateway_sandbox(token)
            log_json("info", "verification result: ok (health 200)", node)

        log_json("info", "rotation complete", node)
        return 0

    except Exception as exc:
        err = str(exc)
        log_json("error", f"rotation failed: {err}", node)
        if not args.dry_run:
            alert_failure(node, err, old_token, secrets_file)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
