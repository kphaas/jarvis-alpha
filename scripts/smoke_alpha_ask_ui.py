#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
UI_DIR = ROOT / "ui"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Smoke the Alpha /ask browser route through the Vite UI."
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("ALPHA_UI_BASE_URL"),
        help="Existing UI base URL. If omitted, starts a local Vite dev server.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("ALPHA_UI_SMOKE_PORT", "5177")),
        help="Local port to use when starting Vite.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.environ.get("ALPHA_UI_SMOKE_TIMEOUT", "20")),
        help="Seconds to wait for the UI route.",
    )
    return parser.parse_args()


def wait_for_route(base_url: str, *, timeout: float) -> str:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    url = f"{base_url.rstrip('/')}/ask"
    request = Request(url, headers={"Accept": "text/html"})

    while time.monotonic() < deadline:
        try:
            with urlopen(request, timeout=2) as response:
                body = response.read().decode("utf-8", errors="replace")
                if response.status == 200 and "AT-0 Alpha" in body and "root" in body:
                    return body
                last_error = RuntimeError(
                    f"unexpected response status={response.status} length={len(body)}"
                )
        except (OSError, URLError) as exc:
            last_error = exc
        time.sleep(0.5)

    raise RuntimeError(f"Alpha /ask route did not become ready: {last_error}")


def port_is_open(port: int) -> bool:
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def start_vite(port: int) -> subprocess.Popen[str]:
    return subprocess.Popen(
        ["npm", "run", "dev", "--", "--host", "127.0.0.1", "--port", str(port)],
        cwd=UI_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def main() -> int:
    args = parse_args()
    proc: subprocess.Popen[str] | None = None
    base_url = args.base_url or f"http://127.0.0.1:{args.port}"

    if args.base_url is None and not port_is_open(args.port):
        proc = start_vite(args.port)

    try:
        wait_for_route(base_url, timeout=args.timeout)
    finally:
        if proc is not None:
            proc.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=5)
            if proc.poll() is None:
                proc.kill()

    print(f"alpha_ask_ui_route=passed base_url={base_url} route=/ask")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"alpha_ask_ui_route=failed error={exc}", file=sys.stderr)
        raise SystemExit(1)
