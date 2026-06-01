#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import http.server
import json
import secrets
import shlex
import subprocess
import sys
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timezone
from http import HTTPStatus

DEFAULT_HOST = "jarvisbrain@jarvis-brain.tail40ed36.ts.net"
DEFAULT_PORT = 53684
GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def _run_ssh(
    host: str, command: str, *, stdin: bytes | None = None
) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["ssh", host, command],
        input=stdin,
        capture_output=True,
        check=False,
    )


def _brain_gmail_client(host: str) -> dict[str, str]:
    remote = """
set -a
source ~/jarvis/.secrets
set +a
python3 - <<'PY'
import json, os
print(json.dumps({
  "client_id": os.environ.get("ALPHA_GMAIL_CLIENT_ID", ""),
  "client_secret": os.environ.get("ALPHA_GMAIL_CLIENT_SECRET", ""),
}))
PY
"""
    result = subprocess.run(
        ["ssh", host, "bash -s"],
        input=remote.encode(),
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode(errors="replace").strip())
    payload = json.loads(result.stdout.decode())
    if not payload.get("client_id") or not payload.get("client_secret"):
        raise RuntimeError(
            "ALPHA_GMAIL_CLIENT_ID or ALPHA_GMAIL_CLIENT_SECRET is missing on Brain"
        )
    return payload


def _auth_url(*, client_id: str, redirect_uri: str, state: str) -> str:
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": GMAIL_READONLY_SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
            "state": state,
        }
    )


def _wait_for_callback(*, port: int, state: str) -> str:
    result: dict[str, str] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:
            return

        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            if parsed.path != "/oauth2callback":
                self.send_response(HTTPStatus.NOT_FOUND)
                self.end_headers()
                return
            if params.get("state", [None])[0] != state:
                result["error"] = "state_mismatch"
            elif params.get("error"):
                result["error"] = params.get("error", ["unknown"])[0]
            else:
                result["code"] = params.get("code", [""])[0]
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<html><body style='font-family:sans-serif'>"
                b"<h2>Gmail connected for JARVIS Alpha.</h2>"
                b"<p>You can close this tab.</p></body></html>"
            )

    with http.server.HTTPServer(("127.0.0.1", port), Handler) as server:
        server.timeout = 300
        while not result:
            server.handle_request()

    if result.get("error"):
        raise RuntimeError(f"OAuth callback failed: {result['error']}")
    code = result.get("code")
    if not code:
        raise RuntimeError("OAuth callback did not include an authorization code")
    return code


def _exchange_code(
    *,
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
) -> str:
    body = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        }
    ).encode()
    try:
        request = urllib.request.Request(TOKEN_URL, data=body, method="POST")
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:500]
        raise RuntimeError(
            f"Google token exchange failed: HTTP {exc.code} {detail}"
        ) from exc
    refresh_token = payload.get("refresh_token")
    if not refresh_token:
        raise RuntimeError(
            "Google did not return a refresh token; retry consent with prompt=consent"
        )
    return str(refresh_token)


def _update_brain_secrets(host: str, refresh_token: str) -> None:
    issued_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    payload = base64.b64encode(
        json.dumps(
            {
                "ALPHA_GMAIL_REFRESH_TOKEN": refresh_token,
                "ALPHA_GMAIL_REFRESH_TOKEN_ISSUED_AT": issued_at,
                "ALPHA_GMAIL_OAUTH_MODE": "testing",
                "ALPHA_GMAIL_TEST_TOKEN_DAYS": "7",
            }
        ).encode()
    )
    remote_code = r"""
import base64, json, os, pathlib, re, sys
updates = json.loads(base64.b64decode(sys.stdin.read().strip()).decode())
path = pathlib.Path.home() / "jarvis/.secrets"
text = path.read_text()
for key, value in updates.items():
    line = key + "=" + value
    if re.search(r"^" + re.escape(key) + r"=.*$", text, flags=re.M):
        text = re.sub(r"^" + re.escape(key) + r"=.*$", line, text, flags=re.M)
    else:
        text = text.rstrip() + "\n" + line + "\n"
path.write_text(text)
os.chmod(path, 0o600)
print("UPDATED_ALPHA_GMAIL_SECRETS")
"""
    command = "python3 -c " + shlex.quote(remote_code)
    result = _run_ssh(host, command, stdin=payload)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode(errors="replace").strip())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reconnect Alpha Gmail OAuth from this Mac"
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="SSH target for Brain")
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT, help="Local callback port"
    )
    parser.add_argument(
        "--no-browser", action="store_true", help="Print URL only; do not open browser"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        creds = _brain_gmail_client(args.host)
        state = secrets.token_urlsafe(24)
        redirect_uri = f"http://127.0.0.1:{args.port}/oauth2callback"
        url = _auth_url(
            client_id=creds["client_id"], redirect_uri=redirect_uri, state=state
        )
        print("Open this URL to reconnect Gmail:")
        print(url)
        if not args.no_browser:
            webbrowser.open(url)
        code = _wait_for_callback(port=args.port, state=state)
        refresh_token = _exchange_code(
            client_id=creds["client_id"],
            client_secret=creds["client_secret"],
            code=code,
            redirect_uri=redirect_uri,
        )
        _update_brain_secrets(args.host, refresh_token)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print("Gmail refresh token updated on Brain. Restart Alpha Brain before testing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
