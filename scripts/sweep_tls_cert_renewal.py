#!/usr/bin/env python3
"""Sweep-managed Tailscale certificate renewal for Alpha service nodes.

The scheduled path is node-local: each node checks or renews its own
certificate, then posts a signed result to Brain for Warden/Porchlight
visibility. The central ``--node all`` path remains a manual operator helper.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import shlex
import socket
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parent.parent
NODE_MAP_PATH = REPO_ROOT / "scripts" / "node_ssh_map.json"
PSQL_BIN = "/opt/homebrew/Cellar/postgresql@16/16.13/bin/psql"
PSQL_DB = "jarvis_alpha"
PSQL_USER = "jarvisbrain"
BRAIN_SSH_TARGET = "jarvisbrain@jarvis-brain.tail40ed36.ts.net"
DEFAULT_REPORT_URL = (
    "https://jarvis-brain.tail40ed36.ts.net:8186/v1/security/sweep-report"
)
REPORT_SECRET_NAME = "ALPHA_SWEEP_REPORT_SECRET"


@dataclass(frozen=True)
class NodeSpec:
    node: str
    fqdn: str
    cert_name: str
    service_label: str | None
    health_url: str | None
    reload_kind: str
    cert_dir: str = "~/jarvis/certs"
    health_fallback_urls: tuple[str, ...] = ()

    @property
    def cert_path(self) -> str:
        return f"{self.cert_dir}/{self.cert_name}.crt"

    @property
    def key_path(self) -> str:
        return f"{self.cert_dir}/{self.cert_name}.key"

    @property
    def fqdn_cert_path(self) -> str:
        return f"{self.cert_dir}/{self.fqdn}.crt"

    @property
    def fqdn_key_path(self) -> str:
        return f"{self.cert_dir}/{self.fqdn}.key"


NODE_SPECS: dict[str, NodeSpec] = {
    "brain": NodeSpec(
        node="brain",
        fqdn="jarvis-brain.tail40ed36.ts.net",
        cert_name="brain",
        service_label="com.jarvis.alpha.brain",
        health_url="https://jarvis-brain.tail40ed36.ts.net:8186/health",
        reload_kind="launchctl",
    ),
    "gateway": NodeSpec(
        node="gateway",
        fqdn="jarvis-gateway.tail40ed36.ts.net",
        cert_name="gateway",
        service_label="com.jarvis.alpha.gateway",
        health_url="https://jarvis-gateway.tail40ed36.ts.net:8283/health",
        reload_kind="launchctl",
    ),
    "endpoint": NodeSpec(
        node="endpoint",
        fqdn="jarvis-endpoint.tail40ed36.ts.net",
        cert_name="endpoint",
        service_label="com.jarvis.nginx",
        health_url="https://jarvis-endpoint.tail40ed36.ts.net:4100",
        reload_kind="launchctl",
    ),
    "sandbox": NodeSpec(
        node="sandbox",
        fqdn="jarvis-sandbox.tail40ed36.ts.net",
        cert_name="sandbox",
        service_label=None,
        health_url="https://jarvis-sandbox.tail40ed36.ts.net:5001/api/health",
        reload_kind="none",
        health_fallback_urls=("https://127.0.0.1:5001/api/health",),
    ),
}


@dataclass
class NodeResult:
    node: str
    fqdn: str
    status: str
    days_remaining: int | None
    cert_issued_at: str | None
    cert_expires_at: str | None
    source_cert: str
    renewed: bool = False
    restarted: bool = False
    health_ok: bool | None = None
    error: str | None = None


def run_command(
    args: list[str],
    *,
    timeout: int = 60,
    input_text: str | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        input=input_text,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=env,
    )


def load_secret(name: str, *, secrets_file: Path | None = None) -> str | None:
    env_value = os.getenv(name, "").strip()
    if env_value:
        return env_value
    path = secrets_file or Path(os.getenv("SECRETS_FILE", "~/.secrets")).expanduser()
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            raw = line.strip()
            if not raw or raw.startswith("#") or "=" not in raw:
                continue
            key, value = raw.split("=", 1)
            if key.strip() != name:
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            return value or None
    except FileNotFoundError:
        return None
    return None


def sweep_report_body(
    result: NodeResult,
    *,
    threshold_days: int,
    reported_at: datetime | None = None,
) -> bytes:
    payload = {
        **asdict(result),
        "threshold_days": threshold_days,
        "reported_at": (reported_at or datetime.now(timezone.utc)).isoformat(),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_report_body(secret: str, *, timestamp: str, body: bytes) -> str:
    message = timestamp.encode("utf-8") + b"." + body
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def post_sweep_report(
    result: NodeResult,
    *,
    threshold_days: int,
    report_url: str | None,
    secret: str | None,
    timeout: int = 12,
) -> dict[str, Any]:
    if not report_url:
        return {"posted": False, "reason": "missing_report_url"}
    if not secret:
        return {"posted": False, "reason": "missing_report_secret"}
    body = sweep_report_body(result, threshold_days=threshold_days)
    timestamp = str(int(time.time()))
    signature = sign_report_body(secret, timestamp=timestamp, body=body)
    request = Request(
        report_url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Jarvis-Node": result.node,
            "X-Jarvis-Timestamp": timestamp,
            "X-Jarvis-Signature": signature,
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 0) or 0)
            return {"posted": 200 <= status < 300, "status": status}
    except HTTPError as exc:
        return {"posted": False, "status": exc.code, "reason": "http_error"}
    except (OSError, URLError, TimeoutError) as exc:
        return {"posted": False, "reason": exc.__class__.__name__}


def load_node_map() -> dict[str, dict[str, str]]:
    return json.loads(NODE_MAP_PATH.read_text(encoding="utf-8"))


def parse_openssl_time(raw: str) -> datetime:
    value = raw.strip().replace("notBefore=", "").replace("notAfter=", "")
    return datetime.strptime(value, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)


def cert_dates(cert_path: Path) -> tuple[datetime, datetime]:
    out = run_command(
        ["openssl", "x509", "-noout", "-startdate", "-enddate", "-in", str(cert_path)],
        timeout=15,
    )
    if out.returncode != 0:
        detail = (out.stderr or out.stdout).strip()
        raise RuntimeError(f"openssl failed for {cert_path}: {detail}")
    values: dict[str, datetime] = {}
    for line in out.stdout.splitlines():
        if line.startswith("notBefore="):
            values["start"] = parse_openssl_time(line)
        elif line.startswith("notAfter="):
            values["end"] = parse_openssl_time(line)
    if "start" not in values or "end" not in values:
        raise RuntimeError(f"openssl did not return start/end dates for {cert_path}")
    return values["start"], values["end"]


def days_remaining(expires_at: datetime, *, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    return int((expires_at - now).total_seconds() // 86400)


def should_renew(days_left: int, threshold_days: int, *, force: bool) -> bool:
    return force or days_left <= threshold_days


def min_validity_duration(threshold_days: int) -> str:
    return f"{max(1, threshold_days) * 24}h"


def cert_moved_forward(previous_expires_at: datetime, new_expires_at: datetime) -> bool:
    return new_expires_at > previous_expires_at


def current_node_guess() -> str | None:
    env_node = os.getenv("JARVIS_NODE", "").strip().lower()
    if env_node in NODE_SPECS:
        return env_node
    host = socket.gethostname().lower()
    for node in NODE_SPECS:
        if host.startswith(f"jarvis-{node}"):
            return node
    return None


def restart_local_service(spec: NodeSpec) -> bool | None:
    if spec.reload_kind == "none" or not spec.service_label:
        return None
    if spec.reload_kind == "launchctl":
        result = run_command(
            [
                "launchctl",
                "kickstart",
                "-k",
                f"gui/{os.getuid()}/{spec.service_label}",
            ],
            timeout=30,
        )
        return result.returncode == 0
    raise RuntimeError(f"unsupported reload kind: {spec.reload_kind}")


def check_health(
    url: str | None,
    fallback_urls: tuple[str, ...] = (),
) -> bool | None:
    urls = tuple(candidate for candidate in (url, *fallback_urls) if candidate)
    if not urls:
        return None
    for candidate in urls:
        result = run_command(
            [
                "curl",
                "-sk",
                "--max-time",
                "12",
                "-o",
                "/dev/null",
                "-w",
                "%{http_code}",
                candidate,
            ],
            timeout=15,
        )
        code = (result.stdout or "").strip()
        if result.returncode == 0 and code.startswith(("2", "3")):
            return True
    return False


def renew_local_node(
    spec: NodeSpec,
    *,
    threshold_days: int,
    force: bool,
    dry_run: bool,
    no_restart: bool,
) -> NodeResult:
    cert_path = Path(spec.cert_path).expanduser()
    fqdn_cert_path = Path(spec.fqdn_cert_path).expanduser()
    source_path = cert_path if cert_path.is_file() else fqdn_cert_path
    if not source_path.is_file():
        return NodeResult(
            node=spec.node,
            fqdn=spec.fqdn,
            status="error",
            days_remaining=None,
            cert_issued_at=None,
            cert_expires_at=None,
            source_cert=str(source_path),
            error=f"certificate not found at {source_path}",
        )

    initial_issued_at, initial_expires_at = cert_dates(source_path)
    days_left = days_remaining(initial_expires_at)
    if not should_renew(days_left, threshold_days, force=force):
        return NodeResult(
            node=spec.node,
            fqdn=spec.fqdn,
            status="ok",
            days_remaining=days_left,
            cert_issued_at=initial_issued_at.isoformat(),
            cert_expires_at=initial_expires_at.isoformat(),
            source_cert=str(source_path),
            health_ok=check_health(spec.health_url, spec.health_fallback_urls),
        )

    if dry_run:
        return NodeResult(
            node=spec.node,
            fqdn=spec.fqdn,
            status="would_renew",
            days_remaining=days_left,
            cert_issued_at=initial_issued_at.isoformat(),
            cert_expires_at=initial_expires_at.isoformat(),
            source_cert=str(source_path),
            renewed=False,
        )

    cert_dir = Path(spec.cert_dir).expanduser()
    cert_dir.mkdir(parents=True, exist_ok=True)
    tailscale = "/opt/homebrew/bin/tailscale"
    result = run_command(
        [
            tailscale,
            "cert",
            "--min-validity",
            min_validity_duration(threshold_days),
            "--cert-file",
            str(fqdn_cert_path),
            "--key-file",
            str(Path(spec.fqdn_key_path).expanduser()),
            spec.fqdn,
        ],
        timeout=120,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        if "alreadyReplaced" in detail:
            health_ok = check_health(spec.health_url, spec.health_fallback_urls)
            return NodeResult(
                node=spec.node,
                fqdn=spec.fqdn,
                status="renewal_pending",
                days_remaining=days_left,
                cert_issued_at=initial_issued_at.isoformat(),
                cert_expires_at=initial_expires_at.isoformat(),
                source_cert=str(source_path),
                renewed=False,
                restarted=False,
                health_ok=health_ok,
                error="tailscale reports an ACME replacement order is already pending",
            )
        return NodeResult(
            node=spec.node,
            fqdn=spec.fqdn,
            status="error",
            days_remaining=days_left,
            cert_issued_at=initial_issued_at.isoformat(),
            cert_expires_at=initial_expires_at.isoformat(),
            source_cert=str(source_path),
            error=f"tailscale cert failed: {detail[:300]}",
        )

    if spec.cert_name != spec.fqdn:
        cert_path.write_bytes(fqdn_cert_path.read_bytes())
        key_path = Path(spec.key_path).expanduser()
        key_path.write_bytes(Path(spec.fqdn_key_path).expanduser().read_bytes())
        os.chmod(cert_path, 0o644)
        os.chmod(key_path, 0o600)

    issued_at, expires_at = cert_dates(
        cert_path if cert_path.is_file() else fqdn_cert_path
    )
    if not cert_moved_forward(
        previous_expires_at=initial_expires_at,
        new_expires_at=expires_at,
    ):
        health_ok = check_health(spec.health_url, spec.health_fallback_urls)
        return NodeResult(
            node=spec.node,
            fqdn=spec.fqdn,
            status="unchanged",
            days_remaining=days_remaining(expires_at),
            cert_issued_at=issued_at.isoformat(),
            cert_expires_at=expires_at.isoformat(),
            source_cert=str(cert_path if cert_path.is_file() else fqdn_cert_path),
            renewed=False,
            restarted=False,
            health_ok=health_ok,
            error="tailscale cert returned the existing certificate",
        )
    restarted = False
    if not no_restart:
        restarted = bool(restart_local_service(spec))
    health_ok = check_health(spec.health_url, spec.health_fallback_urls)
    return NodeResult(
        node=spec.node,
        fqdn=spec.fqdn,
        status="renewed",
        days_remaining=days_remaining(expires_at),
        cert_issued_at=issued_at.isoformat(),
        cert_expires_at=expires_at.isoformat(),
        source_cert=str(cert_path if cert_path.is_file() else fqdn_cert_path),
        renewed=True,
        restarted=restarted,
        health_ok=health_ok,
    )


def run_remote_node(
    node: str,
    *,
    threshold_days: int,
    force: bool,
    dry_run: bool,
    no_restart: bool,
) -> NodeResult:
    node_map = load_node_map()
    target = node_map[node]["ssh_target"]
    command_parts = [
        "python3 scripts/sweep_tls_cert_renewal.py",
        "--local",
        "--node",
        shlex.quote(node),
        "--threshold-days",
        str(threshold_days),
    ]
    if force:
        command_parts.append("--force")
    if dry_run:
        command_parts.append("--dry-run")
    if no_restart:
        command_parts.append("--no-restart")
    remote = "cd ~/jarvis-alpha && " + " ".join(command_parts)
    result = run_command(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            "-o",
            "StrictHostKeyChecking=no",
            target,
            remote,
        ],
        timeout=180,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        return NodeResult(
            node=node,
            fqdn=NODE_SPECS[node].fqdn,
            status="error",
            days_remaining=None,
            cert_issued_at=None,
            cert_expires_at=None,
            source_cert="remote",
            error=f"remote check failed: {detail[:300]}",
        )
    for line in reversed(result.stdout.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            return NodeResult(**json.loads(line))
        except (TypeError, json.JSONDecodeError):
            continue
    return NodeResult(
        node=node,
        fqdn=NODE_SPECS[node].fqdn,
        status="error",
        days_remaining=None,
        cert_issued_at=None,
        cert_expires_at=None,
        source_cert="remote",
        error="remote command returned no JSON result",
    )


def run_node(
    node: str,
    *,
    threshold_days: int,
    force: bool,
    dry_run: bool,
    no_restart: bool,
    current_node: str | None = None,
) -> NodeResult:
    if node == (current_node or current_node_guess()):
        return renew_local_node(
            NODE_SPECS[node],
            threshold_days=threshold_days,
            force=force,
            dry_run=dry_run,
            no_restart=no_restart,
        )
    return run_remote_node(
        node,
        threshold_days=threshold_days,
        force=force,
        dry_run=dry_run,
        no_restart=no_restart,
    )


def build_registry_update_sql(results: list[NodeResult]) -> str:
    statements: list[str] = []
    for result in results:
        if result.status == "error" or not result.cert_expires_at:
            continue
        issued = result.cert_issued_at or result.cert_expires_at
        node = result.node.replace("'", "''")
        statements.append(
            "UPDATE public.alpha_node_registry "
            f"SET cert_issued_at = TIMESTAMPTZ '{issued}', "
            f"cert_expires_at = TIMESTAMPTZ '{result.cert_expires_at}' "
            f"WHERE name = '{node}';"
        )
    return "\n".join(statements)


def sync_registry(results: list[NodeResult]) -> bool:
    sql = build_registry_update_sql(results)
    if not sql.strip():
        return True
    command = (
        "cd ~/jarvis-alpha && set -a && source ~/jarvis/.secrets && set +a && "
        f'PGPASSWORD="$POSTGRES_PASSWORD" {PSQL_BIN} '
        f"-h localhost -U {PSQL_USER} -d {PSQL_DB} -v ON_ERROR_STOP=1 -X -f -"
    )
    if current_node_guess() == "brain":
        result = run_command(["bash", "-lc", command], input_text=sql, timeout=45)
    else:
        result = run_command(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=10",
                "-o",
                "StrictHostKeyChecking=no",
                BRAIN_SSH_TARGET,
                command,
            ],
            input_text=sql,
            timeout=60,
        )
    return result.returncode == 0


def print_json(payload: Any) -> None:
    print(json.dumps(payload, sort_keys=True), flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sweep TLS cert renewal for Alpha")
    parser.add_argument(
        "--node",
        choices=["all", *sorted(NODE_SPECS)],
        default="all",
        help="Node to check/renew, or all service nodes.",
    )
    parser.add_argument("--local", action="store_true", help="Operate on this node.")
    parser.add_argument("--threshold-days", type=int, default=30)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-registry", action="store_true")
    parser.add_argument("--skip-report", action="store_true")
    parser.add_argument(
        "--report-url",
        default=os.getenv("ALPHA_SWEEP_REPORT_URL", DEFAULT_REPORT_URL),
    )
    parser.add_argument("--no-restart", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.local:
        node = args.node if args.node != "all" else current_node_guess()
        if node not in NODE_SPECS:
            print_json({"status": "error", "error": "could not infer local node"})
            return 2
        result = renew_local_node(
            NODE_SPECS[node],
            threshold_days=args.threshold_days,
            force=args.force,
            dry_run=args.dry_run,
            no_restart=args.no_restart,
        )
        if not args.skip_report and not args.dry_run:
            post_sweep_report(
                result,
                threshold_days=args.threshold_days,
                report_url=args.report_url,
                secret=load_secret(REPORT_SECRET_NAME),
            )
        print_json(asdict(result))
        return 1 if result.status == "error" else 0

    nodes = sorted(NODE_SPECS) if args.node == "all" else [args.node]
    current_node = current_node_guess()
    results = [
        run_node(
            node,
            threshold_days=args.threshold_days,
            force=args.force,
            dry_run=args.dry_run,
            no_restart=args.no_restart,
            current_node=current_node,
        )
        for node in nodes
    ]
    registry_synced = True
    if not args.skip_registry and not args.dry_run:
        registry_synced = sync_registry(results)
    payload = {
        "agent_id": "network_watchdog",
        "display_name": "Sweep",
        "task": "service_tls_cert_renewal",
        "threshold_days": args.threshold_days,
        "registry_synced": registry_synced,
        "results": [asdict(result) for result in results],
    }
    print_json(payload)
    has_error = any(result.status == "error" for result in results)
    return 1 if has_error or not registry_synced else 0


if __name__ == "__main__":
    raise SystemExit(main())
