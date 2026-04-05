"""
Dream Mode Kill Switch — emergency stop for running sessions.

Usage:
    python3 -m gateway.dream.kill_switch --session-id 5 --reason "manual emergency stop"
    python3 -m gateway.dream.kill_switch --kill-all --reason "system maintenance"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path


BRAIN_URL = None
ALPHA_SERVICE_TOKEN = None


def _load_config():
    global BRAIN_URL, ALPHA_SERVICE_TOKEN
    BRAIN_URL = os.environ.get("JARVIS_ALPHA_BRAIN_URL")
    ALPHA_SERVICE_TOKEN = os.environ.get("ALPHA_SERVICE_TOKEN")

    if not BRAIN_URL or not ALPHA_SERVICE_TOKEN:
        secrets_path = Path.home() / "jarvis" / ".secrets"
        if secrets_path.exists():
            for line in secrets_path.read_text().splitlines():
                line = line.strip()
                if "=" not in line or line.startswith("#"):
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key == "JARVIS_ALPHA_BRAIN_URL" and not BRAIN_URL:
                    BRAIN_URL = val
                elif key == "ALPHA_SERVICE_TOKEN" and not ALPHA_SERVICE_TOKEN:
                    ALPHA_SERVICE_TOKEN = val

    if not BRAIN_URL:
        print("FATAL: JARVIS_ALPHA_BRAIN_URL not set", file=sys.stderr)
        sys.exit(1)
    if not ALPHA_SERVICE_TOKEN:
        print("FATAL: ALPHA_SERVICE_TOKEN not set", file=sys.stderr)
        sys.exit(1)


async def _curl(method: str, path: str, body: dict | None = None) -> dict:
    url = f"{BRAIN_URL}{path}"
    cmd = ["curl", "-sk", "-X", method, "-H", f"Authorization: Bearer {ALPHA_SERVICE_TOKEN}"]
    if body is not None:
        cmd += ["-H", "Content-Type: application/json", "-d", json.dumps(body)]
    cmd.append(url)
    result = await asyncio.to_thread(
        subprocess.run, cmd, capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        raise RuntimeError(f"curl failed: {result.stderr}")
    if not result.stdout.strip():
        return {}
    return json.loads(result.stdout)


async def kill_session(session_id: int, reason: str):
    _load_config()
    print(f"[KILL] Killing session {session_id}: {reason}")
    result = await _curl("POST", f"/v1/dream/sessions/{session_id}/kill", {"reason": reason})
    print(f"[KILL] Result: {result}")
    return result


async def kill_all(reason: str):
    _load_config()
    sessions = await _curl("GET", "/v1/dream/sessions?limit=50")
    active = [s for s in sessions if s.get("status") in ("pending", "running")]
    if not active:
        print("[KILL] No active sessions found")
        return

    print(f"[KILL] Found {len(active)} active session(s)")
    for s in active:
        sid = s["id"]
        print(f"[KILL] Killing session {sid} ({s['status']}): {reason}")
        try:
            result = await _curl("POST", f"/v1/dream/sessions/{sid}/kill", {"reason": reason})
            print(f"[KILL]   → {result.get('status', 'unknown')}")
        except Exception as e:
            print(f"[KILL]   → ERROR: {e}")


def main():
    parser = argparse.ArgumentParser(description="Dream Mode Kill Switch")
    parser.add_argument("--session-id", type=int, help="Kill a specific session")
    parser.add_argument("--kill-all", action="store_true", help="Kill all active sessions")
    parser.add_argument("--reason", default="manual kill", help="Reason for kill")
    args = parser.parse_args()

    if not args.session_id and not args.kill_all:
        parser.error("Provide --session-id or --kill-all")

    if args.kill_all:
        asyncio.run(kill_all(args.reason))
    else:
        asyncio.run(kill_session(args.session_id, args.reason))


if __name__ == "__main__":
    main()
