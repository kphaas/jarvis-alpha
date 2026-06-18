#!/usr/bin/env python3
"""Porchlight — small scheduled security sweep for JARVIS Alpha.

Porchlight is read-only by design. It scans security posture, writes a JSON
report, and optionally posts one summarized Buddy event through record_buddy_event.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shlex
import socket
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from fnmatch import fnmatch
from pathlib import Path
from typing import Callable
from urllib.parse import quote, urlencode, urlparse

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("SECRETS_FILE", str(Path.home() / "jarvis" / ".secrets"))

from audit_launchagent_drift import parse_launchctl_output  # noqa: E402
from brain.config.node_addresses import GATEWAY_URL  # noqa: E402
from brain.config.secrets import get_secret  # noqa: E402

PSQL_BIN = os.getenv(
    "PORCHLIGHT_PSQL_BIN",
    "/opt/homebrew/Cellar/postgresql@16/16.13/bin/psql",
)
PSQL_DB = os.getenv("PORCHLIGHT_PSQL_DB", "jarvis_alpha")
PSQL_USER = os.getenv("PORCHLIGHT_PSQL_USER", "jarvisbrain")
BRAIN_SSH_TARGET = os.getenv(
    "PORCHLIGHT_BRAIN_SSH_TARGET",
    "jarvisbrain@jarvis-brain.tail40ed36.ts.net",
)
REPORT_PATH = Path(
    os.getenv(
        "PORCHLIGHT_REPORT_PATH",
        str(REPO_ROOT / "logs" / "porchlight_security_report.json"),
    )
)
CLOUDFLARE_ACCESS_URL = os.getenv(
    "PORCHLIGHT_CLOUDFLARE_ACCESS_URL",
    "https://family.kmfh.cloud",
)
CLOUDFLARE_API_BASE = os.getenv(
    "PORCHLIGHT_CLOUDFLARE_API_BASE",
    "https://api.cloudflare.com/client/v4",
)
PORCHLIGHT_CHANNEL_KEY = "security_alerts"
DEFAULT_PORCHLIGHT_SSH_KEY = Path.home() / ".ssh" / "porchlight_monitor"

NODE_MAP_PATH = SCRIPT_DIR / "node_ssh_map.json"
SECRET_ROTATION_CONFIG = SCRIPT_DIR / "secrets_rotation.json"
ROUTES_DIR = REPO_ROOT / "brain" / "routes"
PYTHON_REQUIREMENTS = (REPO_ROOT / "requirements.txt",)
UI_DIR = REPO_ROOT / "ui"
NPM_BIN = os.getenv(
    "PORCHLIGHT_NPM_BIN",
    str(Path("/opt/homebrew/bin/npm"))
    if Path("/opt/homebrew/bin/npm").exists()
    else "npm",
)
FINANCIAL_SECURITY_POSTURE_URL = (
    os.getenv("PORCHLIGHT_FINANCIAL_SECURITY_POSTURE_URL", "").strip()
    or os.getenv("FINANCIAL_SECURITY_POSTURE_URL", "").strip()
)
SECRET_VERIFY_MAX_AGE_HOURS = 36
JWT_VERIFY_MIN_HOURS = 24
RESTORE_DRILL_MAX_AGE_HOURS = int(
    os.getenv("PORCHLIGHT_RESTORE_DRILL_MAX_AGE_HOURS", "192")
)
DEFAULT_CLOUDFLARE_EXPECTED_ACTORS = {"kennethphaas@gmail.com"}
DEFAULT_CLOUDFLARE_FORBIDDEN_HOST_PATTERNS = (
    "alpha.*",
    "brain.*",
    "jarvis-brain.*",
    "*.jarvis-brain.*",
)
DEFAULT_CLOUDFLARE_FORBIDDEN_APP_TERMS = (
    "alpha",
    "brain",
    "jarvis brain",
    "jarvis-brain",
)
DEFAULT_GITHUB_BRANCH_PROTECTION_REPOS = (
    "kphaas/jarvis-alpha",
    "kphaas/jarvis-financial",
    "kphaas/jarvis-forge",
)
DEFAULT_GITHUB_REQUIRED_CHECKS = (
    "forge/native-ci-shadow",
    "github/guardrails",
)
REMOTE_JWT_ALLOWED_KEYS = {
    "ALPHA_SERVICE_TOKEN",
    "ALPHA_SENTINEL_SERVICE_TOKEN",
}
ACCEPTED_BOOTSTRAP_SECDEF_FUNCTIONS = {
    "public.pgaudit_ddl_command_end()",
    "public.pgaudit_sql_drop()",
}

SECURITY_LAUNCHAGENTS: dict[str, set[str]] = {
    "brain": {
        "com.jarvis.alpha.rotate.brain_service",
        "com.jarvis.alpha.rotate.buddy",
        "com.jarvis.alpha.pg_backup",
        "com.jarvis.alpha.gmail-health",
        "com.jarvis.alpha.sweep-cert-renewal.brain",
    },
    "endpoint": {
        "com.jarvis.alpha.rotate.endpoint",
        "com.jarvis.alpha.sweep-cert-renewal.endpoint",
    },
    "gateway": {
        "com.jarvis.alpha.rotate.gateway",
        "com.jarvis.alpha.sweep-cert-renewal.gateway",
    },
    "sandbox": {
        "com.jarvis.alpha.rotate.sandbox",
        "com.jarvis.alpha.restore_drill",
        "com.jarvis.alpha.sweep-cert-renewal.sandbox",
    },
}
SWEEP_TLS_REPORT_EXPECTED_NODES = ("brain", "endpoint", "gateway", "sandbox")
SWEEP_TLS_REPORT_STALE_AFTER = timedelta(hours=24)

TOKEN_LOG_NODES: dict[str, set[str]] = {
    "brain": {"brain", "brain_service"},
    "endpoint": {"endpoint"},
    "gateway": {"gateway"},
    "sandbox": {"sandbox"},
}
TOKEN_LOG_COMMAND = (
    'tail -n 120 "$HOME/jarvis-alpha/logs/token_rotation.log" 2>/dev/null || true'
)
MALWARE_SCAN_DEFAULT_PATHS = (
    "brain",
    "common",
    "config",
    "db",
    "docs",
    "endpoint",
    "gateway",
    "launchagents",
    "scripts",
    ".github/workflows",
)
MALWARE_SCAN_SIBLING_REPOS = (
    "jarvis-family",
    "jarvis-forge",
    "jarvis-financial",
    "jarvis-personality",
    "jarvis-council",
    "jarvis-helm",
    "jarvis-print",
    "jarvis-print-copilot",
    "jarvis-standards",
)
MALWARE_SCAN_SUFFIXES = {
    ".cfg",
    ".cjs",
    ".ini",
    ".js",
    ".json",
    ".mjs",
    ".md",
    ".mdx",
    ".plist",
    ".py",
    ".sh",
    ".sql",
    ".toml",
    ".ts",
    ".tsx",
    ".yaml",
    ".yml",
}
MALWARE_SCAN_EXCLUDED_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "build",
    "dist",
    "logs",
    "node_modules",
}
MALWARE_SCAN_MAX_FILE_BYTES = 1_000_000
MALWARE_SCAN_DEFAULT_ALLOWLIST = {
    "../jarvis-family/scripts/familyvault_pull.sh:macos_persistence_writer",
    "../jarvis-forge/scripts/launchagents/install_inbox_watcher.sh:macos_persistence_writer",
    "brain/services/internet_scout/search_quality_evals.py:sensitive_data_request_instruction",
    "scripts/install_launchagents.py:macos_persistence_writer",
    "scripts/porchlight_security_agent.py:reverse_shell",
    "scripts/porchlight_security_agent.py:bulk_secret_discovery",
    "scripts/porchlight_security_agent.py:sensitive_data_request_instruction",
}
HOST_INTEGRITY_REPO_FILES = (
    "scripts/porchlight_security_agent.py",
    "scripts/porchlight_ssh_probe.sh",
    "scripts/install_launchagents.py",
    "scripts/restore_drill_alpha.sh",
    "scripts/pg_backup_alpha.sh",
    "scripts/sweep_tls_cert_renewal.py",
    "scripts/rotate_secret.py",
    "scripts/rotate_service_token.py",
    "scripts/start_alpha_gmail_health.sh",
    "launchagents/com.jarvis.alpha.porchlight.template.plist",
    "launchagents/com.jarvis.alpha.gmail-health.template.plist",
    "launchagents/com.jarvis.alpha.sweep-cert-renewal.brain.template.plist",
)
HOST_INTEGRITY_BRAIN_FILES = (
    "~/Library/LaunchAgents/com.jarvis.alpha.porchlight.plist",
    "~/Library/LaunchAgents/com.jarvis.alpha.gmail-health.plist",
    "~/Library/LaunchAgents/com.jarvis.alpha.pg_backup.plist",
    "~/Library/LaunchAgents/com.jarvis.alpha.sweep-cert-renewal.brain.plist",
    "~/Library/LaunchAgents/com.jarvis.alpha.rotate.brain_service.plist",
    "~/Library/LaunchAgents/com.jarvis.alpha.rotate.buddy.plist",
)
SECRET_LEAK_LOG_DEFAULT_PATHS = ("logs",)
SECRET_LEAK_LOG_SUFFIXES = {
    ".err",
    ".json",
    ".jsonl",
    ".log",
    ".out",
    ".txt",
}
SECRET_LEAK_EXCLUDED_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "node_modules",
}
SECRET_LEAK_MAX_FILE_BYTES = int(
    os.getenv("PORCHLIGHT_SECRET_LEAK_MAX_FILE_BYTES", "1048576")
)
SECRET_LEAK_DB_LIMIT = int(os.getenv("PORCHLIGHT_SECRET_LEAK_DB_LIMIT", "250"))
SECRET_LEAK_DB_LOOKBACK_HOURS = int(
    os.getenv("PORCHLIGHT_SECRET_LEAK_DB_LOOKBACK_HOURS", "48")
)
EGRESS_SCAN_DEFAULT_PATHS = (
    "brain",
    "config",
    "gateway",
    "launchagents",
    "scripts",
    ".github/workflows",
)
EGRESS_SCAN_SUFFIXES = {
    ".cfg",
    ".ini",
    ".json",
    ".md",
    ".plist",
    ".py",
    ".sh",
    ".toml",
    ".yaml",
    ".yml",
}
EGRESS_SCAN_EXCLUDED_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "dist",
    "logs",
    "node_modules",
    "tests",
}
EGRESS_LOG_DEFAULT_PATHS = ("logs",)
EGRESS_LOG_NAME_TERMS = ("cloud", "egress", "gateway", "notify", "proxy")
EGRESS_ALLOWED_HOSTS = {
    "127.0.0.1",
    "0.0.0.0",
    "accounts.google.com",
    "api.anthropic.com",
    "api.cloudflare.com",
    "api.github.com",
    "api.open-meteo.com",
    "api.openai.com",
    "api.perplexity.ai",
    "api.pushover.net",
    "api.search.brave.com",
    "api.tailscale.com",
    "aws.amazon.com",
    "brave.com",
    "cloudbilling.googleapis.com",
    "developers.cloudflare.com",
    "docs.anthropic.com",
    "docs.github.com",
    "docs.perplexity.ai",
    "docs.stripe.com",
    "family.kmfh.cloud",
    "generativelanguage.googleapis.com",
    "github.com",
    "gmail.googleapis.com",
    "graph.microsoft.com",
    "jarvis-brain.tail40ed36.ts.net",
    "jarvis-endpoint.tail40ed36.ts.net",
    "jarvis-gateway.tail40ed36.ts.net",
    "localhost",
    "login.microsoftonline.com",
    "oauth2.googleapis.com",
    "platform.openai.com",
    "www.apple.com",
    "www.googleapis.com",
}
EGRESS_ALLOWED_SUFFIXES = (".tail40ed36.ts.net",)
EGRESS_NON_EGRESS_PATH_PARTS = (("brain", "agents", "privacy_scrub", "data"),)
EGRESS_NON_EGRESS_FILES = {
    "brain/routes/honeypot.py",
    "brain/services/internet_scout/search_quality_evals.py",
}
TAILSCALE_DEFAULT_BIN = "/opt/homebrew/bin/tailscale"
TAILSCALE_API_BASE = os.getenv(
    "PORCHLIGHT_TAILSCALE_API_BASE",
    "https://api.tailscale.com/api/v2",
)
TAILSCALE_DEFAULT_STALE_AFTER_DAYS = 30
TAILSCALE_EXPECTED_DNS_BY_NODE = {
    "brain": "jarvis-brain.tail40ed36.ts.net",
    "gateway": "jarvis-gateway.tail40ed36.ts.net",
    "endpoint": "jarvis-endpoint.tail40ed36.ts.net",
    "sandbox": "jarvis-sandbox.tail40ed36.ts.net",
}
EXPECTED_EXTERNAL_LISTENERS = (
    ("python", "8186"),
    ("python", "8187"),
    ("python", "8195"),
    ("loki", "3100"),
    ("rapportd", "49930"),
    ("controlce", "5000"),
    ("controlce", "7000"),
)
SUSPICIOUS_PROCESS_PATTERNS = (
    re.compile(r"\bpython(?:3)?\s+-m\s+http\.server\b", re.IGNORECASE),
    re.compile(r"\b(?:nc|ncat|netcat)\b[^\n]{0,120}\s-l\b", re.IGNORECASE),
    re.compile(r"\bsocat\b[^\n]{0,160}\bLISTEN\b", re.IGNORECASE),
    re.compile(r"bash\s+-i\s+>&\s*(?:/dev/tcp/|/dev/udp/)", re.IGNORECASE),
)
MALWARE_STATIC_PATTERNS = (
    {
        "id": "download_exec_pipe",
        "severity": "critical",
        "summary": "downloaded payload is piped directly into an interpreter",
        "regex": re.compile(
            r"\b(?:curl|wget)\b[^\n|]{0,220}\|\s*(?:/usr/bin/env\s+)?"
            r"(?:(?:/bin/)?(?:bash|sh|zsh|perl|ruby)\b|python(?:3)?\s+-(?:\s|$))",
            re.IGNORECASE,
        ),
    },
    {
        "id": "obfuscated_python_exec",
        "severity": "critical",
        "summary": "base64 or marshal payload is executed dynamically",
        "regex": re.compile(
            r"\b(?:exec|eval)\s*\([^)\n]{0,260}\b"
            r"(?:base64\.b64decode|marshal\.loads|zlib\.decompress)\b"
            r"|\b(?:base64\.b64decode|marshal\.loads|zlib\.decompress)\b"
            r"[\s\S]{0,260}\b(?:exec|eval)\s*\(",
            re.IGNORECASE,
        ),
    },
    {
        "id": "obfuscated_javascript_exec",
        "severity": "critical",
        "summary": "base64 JavaScript payload is executed dynamically",
        "regex": re.compile(
            r"\b(?:eval|Function)\s*\(\s*(?:window\.)?(?:atob|Buffer\.from)\s*\(",
            re.IGNORECASE,
        ),
    },
    {
        "id": "reverse_shell",
        "severity": "critical",
        "summary": "reverse shell primitive appears in source",
        "regex": re.compile(
            r"bash\s+-i\s+>&\s*(?:/dev/tcp/|/dev/udp/)"
            r"|(?:nc|ncat|netcat)\s+[^\n]{0,120}\s-e\s"
            r"|exec\s+\d+<>/dev/tcp/[^\n]{1,160}cat\s+<",
            re.IGNORECASE,
        ),
    },
    {
        "id": "secrets_pipe_to_network",
        "severity": "critical",
        "summary": "secret material appears to be piped to a network tool",
        "regex": re.compile(
            r"(?:\.secrets|POSTGRES_PASSWORD|GITHUB_TOKEN|CLOUDFLARE_API_TOKEN)"
            r"[^\n|]{0,180}\|\s*(?:curl|nc|ncat|netcat)\b"
            r"|(?:curl|nc|ncat|netcat)\b[^\n|]{0,180}<\s*"
            r"(?:~/)?(?:jarvis/)?\.secrets",
            re.IGNORECASE,
        ),
    },
    {
        "id": "env_dump_to_network",
        "severity": "critical",
        "summary": "environment variables appear to be dumped to a network tool",
        "regex": re.compile(
            r"\b(?:env|printenv|set)\b[^\n|]{0,120}\|\s*"
            r"(?:curl|nc|ncat|netcat)\b",
            re.IGNORECASE,
        ),
    },
    {
        "id": "secret_file_direct_read",
        "severity": "critical",
        "summary": "code directly reads sensitive local secret/key files",
        "regex": re.compile(
            r"\b(?:cat|less|more|tail|head)\s+[^\n]{0,180}"
            r"(?:~|\$HOME|/Users|/var/root)[^\n]{0,180}"
            r"(?:\.secrets|\.env|id_rsa|id_ed25519|credentials\.json|token\.json)",
            re.IGNORECASE,
        ),
    },
    {
        "id": "bulk_secret_discovery",
        "severity": "critical",
        "summary": "code appears to search broadly for secrets or private keys",
        "regex": re.compile(
            r"\b(?:find|fd)\s+(?:/|~|\$HOME|/Users|/var/root)[^\n]{0,220}"
            r"(?:-name|-iname)[^\n]{0,120}"
            r"(?:\.secrets|\.env|id_rsa|id_ed25519|credentials\.json|token\.json)"
            r"|\b(?:grep|rg|ag)\b[^\n]{0,80}(?:-R|-r|--recursive)[^\n]{0,120}"
            r"(?:AKIA|BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY|api[_ -]?key|password|token|secret)"
            r"[^\n]{0,220}(?:/|~|\$HOME|/Users|/var/root)",
            re.IGNORECASE,
        ),
    },
    {
        "id": "sensitive_data_request_instruction",
        "severity": "critical",
        "summary": "prompt/instruction text asks for sensitive data disclosure",
        "regex": re.compile(
            r"(?:ignore\s+(?:all\s+)?(?:previous|prior|above|system)\s+instructions|"
            r"bypass\s+(?:policy|guardrails|safety)|do\s+not\s+ask\s+permission)"
            r"[\s\S]{0,260}"
            r"(?:secret|token|password|api[_ -]?key|private\s+key|credentials|"
            r"environment\s+variables|sensitive\s+data)"
            r"|(?:send|post|upload|exfiltrate|dump|reveal|print|return|share)"
            r"[^\n.]{0,140}"
            r"\b(?:all|actual|the|your|my|any|full)\s+"
            r"(?:secrets|tokens|passwords|api[_ -]?keys|private\s+keys|credentials|"
            r"environment\s+variables|\.secrets|sensitive\s+data)",
            re.IGNORECASE,
        ),
    },
    {
        "id": "macos_persistence_writer",
        "severity": "high",
        "summary": "code writes directly into macOS LaunchAgent persistence paths",
        "regex": re.compile(
            r"(?:write_text|open|cp|mv|install)\s*\(?[^\n]{0,180}"
            r"(?:~/)?Library/LaunchAgents/",
            re.IGNORECASE,
        ),
    },
)
SECRET_LEAK_PATTERNS = (
    {
        "id": "private_key_material",
        "severity": "critical",
        "regex": re.compile(
            r"-----BEGIN (?:RSA |OPENSSH |EC |DSA |)?PRIVATE KEY-----",
            re.IGNORECASE,
        ),
    },
    {
        "id": "jwt_token_value",
        "severity": "critical",
        "regex": re.compile(
            r"\b(?P<value>eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
            r"\.[A-Za-z0-9_-]{10,})\b"
        ),
    },
    {
        "id": "github_token_value",
        "severity": "critical",
        "regex": re.compile(
            r"\b(?P<value>(?:github_pat_[A-Za-z0-9_]{22,}|"
            r"gh[pousr]_[A-Za-z0-9_]{20,}))\b"
        ),
    },
    {
        "id": "provider_api_key_value",
        "severity": "critical",
        "regex": re.compile(
            r"\b(?P<value>(?:sk-(?:ant-|proj-|live-|test-)?[A-Za-z0-9_-]{20,}|"
            r"AIza[0-9A-Za-z_-]{32,}|xox[baprs]-[0-9A-Za-z-]{20,}))\b"
        ),
    },
    {
        "id": "bearer_token_value",
        "severity": "high",
        "regex": re.compile(
            r"\bBearer\s+(?P<value>[A-Za-z0-9._~+/=-]{32,})\b",
            re.IGNORECASE,
        ),
    },
    {
        "id": "credential_assignment_value",
        "severity": "high",
        "regex": re.compile(
            r"\b(?:password|passwd|secret|token|api[_-]?key|client[_-]?secret|"
            r"refresh[_-]?token|access[_-]?token)\b"
            r"\s*[:=]\s*[\"']?(?P<value>[A-Za-z0-9_./+=:-]{20,})",
            re.IGNORECASE,
        ),
    },
    {
        "id": "credential_url_value",
        "severity": "high",
        "regex": re.compile(
            r"\b(?:postgres(?:ql)?|mysql|redis|mongodb)://"
            r"[^:\s/@]+:(?P<value>[^@\s]{6,})@",
            re.IGNORECASE,
        ),
    },
    {
        "id": "aws_access_key_value",
        "severity": "high",
        "regex": re.compile(r"\b(?P<value>AKIA[0-9A-Z]{16})\b"),
    },
)
SECRET_PLACEHOLDER_VALUES = {
    "access-token",
    "api-key",
    "bearer-token",
    "changeme",
    "dummy-token",
    "example-token",
    "fake-token",
    "redacted",
    "secret",
    "test-token",
    "token",
}

SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
REVIEWED_ROUTE_DB_ACCESS: dict[str, str] = {
    "briefings.py": "Briefing ingestion/read paths are scope-gated service/admin routes; follow-up is to migrate to explicit service RLS context.",
    "chat.py": "Primary chat persistence uses rls_connection; remaining direct access is a legacy compatibility path pending route split.",
    "costs.py": "Cost collection is admin/service-scoped infrastructure data, not child profile content.",
    "dev.py": "Development-only diagnostics; protected by auth middleware outside explicit skip paths.",
    "dream.py": "Dream control plane uses service/admin paths with platform-admin policies; broader refactor is tracked separately.",
    "dream_planning.py": "Model policy lookup is platform-admin service configuration and sets rls.role inside transaction.",
    "internal_cost.py": "Internal cost ingestion is service-scoped and explicitly checks cost.report scope.",
    "prompts.py": "Prompt registry is global system configuration; write path is auth-protected and pending RLS wrapper.",
    "watchdog.py": "Watchdog ingest path is service-scoped; user-facing events use rls_connection.",
}


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


@dataclass
class CheckResult:
    name: str
    status: str
    severity: str
    summary: str
    detail: str = ""
    metadata: dict[str, object] = field(default_factory=dict)


def run_command(
    args: list[str],
    timeout: int = 30,
    input_text: str | None = None,
    env: dict[str, str] | None = None,
) -> CommandResult:
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            input=input_text,
            text=True,
            timeout=timeout,
            check=False,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CommandResult(1, "", str(exc))
    return CommandResult(result.returncode, result.stdout or "", result.stderr or "")


def _postgres_password() -> str | None:
    password = os.getenv("POSTGRES_PASSWORD", "").strip()
    if password:
        return password
    try:
        return get_secret("POSTGRES_PASSWORD").strip()
    except KeyError:
        return None


def run_psql(query: str, timeout: int = 45) -> CommandResult:
    password = _postgres_password()
    use_password_auth = PSQL_USER == "jarvisbrain" or password is not None
    psql_args = [
        PSQL_BIN,
        *(["-h", "localhost"] if use_password_auth else []),
        "-U",
        PSQL_USER,
        "-d",
        PSQL_DB,
        "-t",
        "-A",
        "-F",
        "|",
        "-f",
        "-",
    ]
    node = os.getenv("JARVIS_NODE", "").strip().lower()
    hostname = socket.gethostname().lower()
    if node == "brain" or hostname.startswith("jarvis-brain"):
        env = os.environ.copy()
        if password:
            env["PGPASSWORD"] = password
        return run_command(psql_args, timeout=timeout, input_text=query, env=env)

    remote_command = " ".join(shlex.quote(part) for part in psql_args)
    remote_command = (
        "cd ~/jarvis-alpha && set -a && source ~/jarvis/.secrets && set +a && "
        f'PGPASSWORD="$POSTGRES_PASSWORD" {remote_command}'
    )
    return run_command(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=8",
            BRAIN_SSH_TARGET,
            remote_command,
        ],
        timeout=timeout,
        input_text=query,
    )


def ssh_args_for_probe() -> list[str]:
    args = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=8",
        "-o",
        "StrictHostKeyChecking=yes",
    ]
    key_path = os.getenv("PORCHLIGHT_SSH_KEY", "").strip()
    expanded = Path(key_path).expanduser() if key_path else DEFAULT_PORCHLIGHT_SSH_KEY
    if expanded.is_file():
        args.extend(["-i", str(expanded), "-o", "IdentitiesOnly=yes"])
    return args


def run_ssh(ssh_target: str, remote_command: str, timeout: int = 30) -> CommandResult:
    result = run_command(
        [*ssh_args_for_probe(), ssh_target, remote_command],
        timeout=timeout,
    )
    if result.returncode == 0 or not _should_retry_with_probe_script(result):
        return result
    fallback = _explicit_probe_script_command(remote_command)
    return run_command([*ssh_args_for_probe(), ssh_target, fallback], timeout=timeout)


def _should_retry_with_probe_script(result: CommandResult) -> bool:
    detail = f"{result.stderr}\n{result.stdout}".lower()
    return (
        "command not found: porchlight" in detail
        or "porchlight: command not found" in detail
    )


def _explicit_probe_script_command(remote_command: str) -> str:
    return (
        "SSH_ORIGINAL_COMMAND="
        f"{shlex.quote(remote_command)} "
        "$HOME/jarvis-alpha/scripts/porchlight_ssh_probe.sh"
    )


def remote_ssh_probe_enabled() -> bool:
    configured = os.getenv("PORCHLIGHT_REMOTE_SSH_ENABLED", "").strip().lower()
    if configured in {"1", "true", "yes"}:
        return True
    key_path = os.getenv("PORCHLIGHT_SSH_KEY", "").strip()
    expanded = Path(key_path).expanduser() if key_path else DEFAULT_PORCHLIGHT_SSH_KEY
    if expanded.is_file():
        return True
    return current_node_name() is None


def current_node_name() -> str | None:
    node = os.getenv("JARVIS_NODE", "").strip().lower()
    if node in SECURITY_LAUNCHAGENTS:
        return node

    hostname = socket.gethostname().lower()
    if hostname.startswith("jarvis-brain"):
        return "brain"
    if hostname.startswith("jarvis-endpoint"):
        return "endpoint"
    if hostname.startswith("jarvis-gateway"):
        return "gateway"
    if hostname.startswith("jarvis-sandbox"):
        return "sandbox"
    return None


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_psql_rows(output: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for raw in output.splitlines():
        line = raw.strip()
        if not line or "|" not in line:
            continue
        rows.append([part.strip() for part in line.split("|")])
    return rows


def highest_severity(results: list[CheckResult]) -> str:
    severity = "info"
    for result in results:
        if SEVERITY_RANK[result.severity] > SEVERITY_RANK[severity]:
            severity = result.severity
    return severity


def check_database_rls(psql: Callable[[str], CommandResult] = run_psql) -> CheckResult:
    query = """
SELECT c.relname,
       c.relrowsecurity::text,
       c.relforcerowsecurity::text,
       COALESCE(p.policy_count, 0)::text
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN (
    SELECT polrelid, COUNT(*) AS policy_count
    FROM pg_policy
    GROUP BY polrelid
) p ON p.polrelid = c.oid
WHERE n.nspname = 'public'
  AND c.relkind = 'r'
  AND c.relname NOT IN ('schema_migrations')
ORDER BY c.relname;
""".strip()
    result = psql(query)
    if result.returncode != 0:
        return CheckResult(
            name="database_rls",
            status="fail",
            severity="critical",
            summary="Could not inspect database RLS posture.",
            detail=(result.stderr or result.stdout).strip()[:500],
        )

    rows = parse_psql_rows(result.stdout)
    if not rows:
        return CheckResult(
            name="database_rls",
            status="warn",
            severity="medium",
            summary="No database table rows were returned for RLS inspection.",
        )

    disabled: list[str] = []
    not_force: list[str] = []
    no_policy: list[str] = []
    for table, rls_enabled, force_enabled, policy_count in rows:
        if rls_enabled != "true":
            disabled.append(table)
        if force_enabled != "true":
            not_force.append(table)
        if policy_count == "0":
            no_policy.append(table)

    issues = []
    if disabled:
        issues.append(f"RLS disabled: {', '.join(disabled[:8])}")
    if not_force:
        issues.append(f"FORCE RLS missing: {', '.join(not_force[:8])}")
    if no_policy:
        issues.append(f"No RLS policy: {', '.join(no_policy[:8])}")

    if disabled or not_force:
        return CheckResult(
            name="database_rls",
            status="fail",
            severity="critical" if disabled else "high",
            summary="Database RLS posture needs attention.",
            detail="; ".join(issues),
            metadata={
                "total_tables": len(rows),
                "disabled": disabled,
                "not_force": not_force,
                "no_policy": no_policy,
            },
        )

    if no_policy:
        return CheckResult(
            name="database_rls",
            status="warn",
            severity="medium",
            summary="All tables have FORCE RLS, but some have no policy.",
            detail="; ".join(issues),
            metadata={"total_tables": len(rows), "no_policy": no_policy},
        )

    return CheckResult(
        name="database_rls",
        status="pass",
        severity="info",
        summary=f"RLS and FORCE RLS are enabled on {len(rows)} public tables.",
        metadata={"total_tables": len(rows)},
    )


def check_postgres_role_safety(
    psql: Callable[[str], CommandResult] = run_psql,
) -> CheckResult:
    query = """
SELECT rolname,
       rolsuper::text,
       rolbypassrls::text,
       rolcreatedb::text,
       rolcreaterole::text,
       rolcanlogin::text,
       oid::text
FROM pg_roles
WHERE rolname IN (
    'jarvisbrain',
    'jarvis_alpha_writer',
    'jarvis_alpha_app',
    'jarvis_alpha_owner',
    'jarvis_pg_breakglass'
)
   OR rolsuper
ORDER BY rolname;
""".strip()
    result = psql(query)
    if result.returncode != 0:
        return CheckResult(
            name="postgres_role_safety",
            status="fail",
            severity="critical",
            summary="Could not inspect Postgres role safety posture.",
            detail=(result.stderr or result.stdout).strip()[:500],
        )

    rows = parse_psql_rows(result.stdout)
    if not rows:
        return CheckResult(
            name="postgres_role_safety",
            status="fail",
            severity="critical",
            summary="No Postgres role rows were returned for safety inspection.",
        )

    roles = {
        row[0]: {
            "rolsuper": row[1] == "true",
            "rolbypassrls": row[2] == "true",
            "rolcreatedb": row[3] == "true",
            "rolcreaterole": row[4] == "true",
            "rolcanlogin": row[5] == "true",
            "oid": row[6] if len(row) >= 7 else "",
        }
        for row in rows
        if len(row) >= 6
    }
    missing_required = sorted(
        {"jarvisbrain", "jarvis_alpha_writer", "jarvis_alpha_app"} - set(roles)
    )
    missing_containment = sorted(
        {"jarvis_alpha_owner", "jarvis_pg_breakglass"} - set(roles)
    )
    superusers = sorted(
        name for name, attrs in roles.items() if attrs.get("rolsuper") is True
    )
    runtime_bypass = sorted(
        name
        for name in ("jarvis_alpha_writer", "jarvis_alpha_app")
        if roles.get(name, {}).get("rolsuper")
        or roles.get(name, {}).get("rolbypassrls")
    )

    issues: list[str] = []
    if missing_required:
        issues.append("missing required role(s): " + ", ".join(missing_required))
    if runtime_bypass:
        issues.append("runtime role(s) can bypass RLS: " + ", ".join(runtime_bypass))
    jarvisbrain_superuser = roles.get("jarvisbrain", {}).get("rolsuper") is True
    secdef_metadata: dict[str, object] = {}
    if jarvisbrain_superuser:
        if roles.get("jarvisbrain", {}).get("rolbypassrls"):
            issues.append("jarvisbrain still has BYPASSRLS")
        if roles.get("jarvisbrain", {}).get("oid") != "10":
            issues.append("jarvisbrain is SUPERUSER and is not the bootstrap role")
        if missing_containment:
            issues.append(
                "missing bootstrap containment role(s): "
                + ", ".join(missing_containment)
            )
        if superusers == ["jarvisbrain"]:
            issues.append(
                "jarvisbrain is the only superuser; demotion needs break-glass first"
            )
        if not issues:
            secdef_ok, secdef_detail, secdef_metadata = (
                _check_security_definer_owner_containment(psql)
            )
            if not secdef_ok:
                issues.append(secdef_detail)

    if jarvisbrain_superuser and issues:
        issues.insert(
            0,
            "jarvisbrain is still SUPERUSER and can bypass FORCE RLS until containment is complete",
        )

    if issues:
        return CheckResult(
            name="postgres_role_safety",
            status="fail",
            severity="critical",
            summary="Postgres role safety needs remediation before strict production readiness.",
            detail="; ".join(issues),
            metadata={
                "superusers": superusers,
                "runtime_bypass_roles": runtime_bypass,
                "missing_required_roles": missing_required,
                "missing_containment_roles": missing_containment,
                "jarvisbrain": roles.get("jarvisbrain", {}),
                "security_definer": secdef_metadata,
                "accepted_exception": None,
            },
        )

    if jarvisbrain_superuser:
        return CheckResult(
            name="postgres_role_safety",
            status="warn",
            severity="medium",
            summary="Postgres bootstrap superuser risk is accepted and contained.",
            detail=(
                "jarvisbrain remains a bootstrap superuser, but runtime roles are "
                "NOBYPASSRLS, break-glass exists, and SECURITY DEFINER functions "
                "are owned by jarvis_alpha_owner except accepted pgaudit handlers."
            ),
            metadata={
                "superusers": superusers,
                "runtime_bypass_roles": runtime_bypass,
                "missing_required_roles": missing_required,
                "missing_containment_roles": missing_containment,
                "jarvisbrain": roles.get("jarvisbrain", {}),
                "security_definer": secdef_metadata,
                "bootstrap_risk": "accepted_contained",
                "accepted_exception": "postgres_bootstrap_role_superuser",
            },
        )

    return CheckResult(
        name="postgres_role_safety",
        status="pass",
        severity="info",
        summary="Postgres runtime roles are NOBYPASSRLS and jarvisbrain is not superuser.",
        metadata={"superusers": superusers},
    )


def _check_security_definer_owner_containment(
    psql: Callable[[str], CommandResult],
) -> tuple[bool, str, dict[str, object]]:
    query = """
SELECT format('%I.%I(%s)',
              n.nspname,
              p.proname,
              pg_get_function_identity_arguments(p.oid)),
       pg_get_userbyid(p.proowner),
       l.lanname
FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
JOIN pg_language l ON l.oid = p.prolang
WHERE p.prosecdef
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND n.nspname NOT LIKE 'pg_toast%'
ORDER BY n.nspname, p.proname, pg_get_function_identity_arguments(p.oid);
""".strip()
    result = psql(query)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[:500]
        return (
            False,
            "could not inspect SECURITY DEFINER ownership: " + detail,
            {"error": detail},
        )

    rows = parse_psql_rows(result.stdout)
    if not rows:
        return False, "no SECURITY DEFINER rows returned", {"total": 0}

    owner_counts: dict[str, int] = {}
    accepted_bootstrap: list[str] = []
    unexpected: list[str] = []
    malformed = 0
    for row in rows:
        if len(row) < 3:
            malformed += 1
            continue
        identity, owner, language = row[:3]
        owner_counts[owner] = owner_counts.get(owner, 0) + 1
        if owner == "jarvis_alpha_owner":
            continue
        if (
            owner == "jarvisbrain"
            and language == "c"
            and identity in ACCEPTED_BOOTSTRAP_SECDEF_FUNCTIONS
        ):
            accepted_bootstrap.append(identity)
            continue
        unexpected.append(f"{identity} owned by {owner}")

    metadata = {
        "total": len(rows),
        "owner_counts": owner_counts,
        "accepted_bootstrap": accepted_bootstrap,
        "unexpected": unexpected,
        "malformed_rows": malformed,
    }
    if malformed:
        return (
            False,
            f"{malformed} SECURITY DEFINER row(s) could not be parsed",
            metadata,
        )
    if unexpected:
        return (
            False,
            "unexpected SECURITY DEFINER owner(s): " + "; ".join(unexpected[:5]),
            metadata,
        )
    return True, "", metadata


def _pg_hba_csv_items(value: str) -> set[str]:
    cleaned = value.strip().strip("{}")
    if not cleaned:
        return set()
    return {part.strip().strip('"') for part in cleaned.split(",") if part.strip()}


def check_postgres_hba_safety(
    psql: Callable[[str], CommandResult] = run_psql,
) -> CheckResult:
    query = """
SELECT line_number::text,
       type,
       array_to_string(database, ','),
       array_to_string(user_name, ','),
       COALESCE(address, ''),
       auth_method,
       COALESCE(error, '')
FROM pg_hba_file_rules
ORDER BY line_number;
""".strip()
    result = psql(query)
    if result.returncode != 0:
        return CheckResult(
            name="postgres_hba_safety",
            status="fail",
            severity="critical",
            summary="Could not inspect Postgres client authentication rules.",
            detail=(result.stderr or result.stdout).strip()[:500],
        )

    rows = parse_psql_rows(result.stdout)
    if not rows:
        return CheckResult(
            name="postgres_hba_safety",
            status="fail",
            severity="critical",
            summary="No pg_hba rules were returned for safety inspection.",
        )

    broad_trust_rules: list[str] = []
    parser_errors: list[str] = []
    malformed_rows = 0
    trust_rule_count = 0

    for row in rows:
        if len(row) < 7:
            malformed_rows += 1
            continue
        (
            line_number,
            rule_type,
            databases_raw,
            users_raw,
            address,
            auth_method,
            error,
        ) = row[:7]
        if error:
            parser_errors.append(f"line {line_number}: {error[:120]}")
        if auth_method != "trust":
            continue

        trust_rule_count += 1
        databases = _pg_hba_csv_items(databases_raw)
        users = _pg_hba_csv_items(users_raw)
        is_loopback = address in {"", "127.0.0.1", "127.0.0.1/32", "::1", "::1/128"}
        is_broad = "all" in databases and "all" in users
        if (
            rule_type in {"local", "host", "hostssl", "hostnossl"}
            and is_loopback
            and is_broad
        ):
            if rule_type == "local":
                broad_trust_rules.append(f"line {line_number}: local all/all trust")
            else:
                broad_trust_rules.append(
                    f"line {line_number}: {rule_type} {address} all/all trust"
                )

    issues = []
    if parser_errors:
        issues.append("pg_hba parse errors: " + "; ".join(parser_errors[:3]))
    if malformed_rows:
        issues.append(f"{malformed_rows} pg_hba row(s) could not be parsed")
    if broad_trust_rules:
        issues.append("broad local trust auth: " + "; ".join(broad_trust_rules[:5]))

    if issues:
        return CheckResult(
            name="postgres_hba_safety",
            status="fail",
            severity="critical",
            summary="Postgres client authentication is not safe for break-glass demotion.",
            detail="; ".join(issues),
            metadata={
                "total_rules": len(rows),
                "trust_rule_count": trust_rule_count,
                "broad_trust_rules": broad_trust_rules,
                "parser_errors": parser_errors,
                "malformed_rows": malformed_rows,
            },
        )

    return CheckResult(
        name="postgres_hba_safety",
        status="pass",
        severity="info",
        summary="Postgres client authentication has no broad local trust rules.",
        metadata={"total_rules": len(rows), "trust_rule_count": trust_rule_count},
    )


def check_secret_rotation(
    psql: Callable[[str], CommandResult] = run_psql,
    config_path: Path = SECRET_ROTATION_CONFIG,
    today: date | None = None,
) -> CheckResult:
    today = today or datetime.now(UTC).date()
    query = """
SELECT set_config('rls.role', 'platform_admin', false);
SELECT secret_name,
       COALESCE(last_rotated_at::date::text, ''),
       rotation_days::text,
       next_due_at::text,
       days_until_due::text,
       COALESCE(last_verify_status, '')
FROM v_secret_rotation_status
ORDER BY secret_name;
""".strip()
    result = psql(query)
    if result.returncode != 0:
        return CheckResult(
            name="secret_rotation",
            status="fail",
            severity="high",
            summary="Could not inspect secret rotation ledger.",
            detail=(result.stderr or result.stdout).strip()[:500],
        )

    rows = parse_psql_rows(result.stdout)
    config = load_json(config_path)
    configured = config.get("secrets", {})
    seen: dict[str, dict[str, str]] = {}
    issues: list[str] = []
    warnings: list[str] = []

    for row in rows:
        if len(row) < 6:
            continue
        name, rotated, days, next_due, days_until, verify = row[:6]
        seen[name] = {
            "last_rotated": rotated,
            "rotation_days": days,
            "next_due_at": next_due,
            "days_until_due": days_until,
            "last_verify_status": verify,
        }
        due_date = datetime.strptime(next_due, "%Y-%m-%d").date()
        days_left = (due_date - today).days
        try:
            rotation_days = int(days)
        except ValueError:
            rotation_days = 14
        warning_window_days = min(14, max(1, (rotation_days + 3) // 4))
        if verify == "failed":
            issues.append(f"{name} last verification failed")
        if days_left < 0:
            issues.append(f"{name} overdue since {next_due}")
        elif days_left == 0:
            issues.append(f"{name} due today")
        elif days_left <= warning_window_days:
            warnings.append(f"{name} due in {days_left} days")

    for name, spec in configured.items():
        if name in seen:
            continue
        if spec.get("requires_alter_role"):
            warnings.append(f"{name} is manual DB rotation and has no ledger row")
        else:
            issues.append(f"{name} missing from rotation ledger")

    if issues:
        return CheckResult(
            name="secret_rotation",
            status="fail",
            severity="critical",
            summary="One or more secrets are due, overdue, failed, or untracked.",
            detail="; ".join((issues + warnings)[:10]),
            metadata={"issues": issues, "warnings": warnings, "secrets": seen},
        )

    if warnings:
        return CheckResult(
            name="secret_rotation",
            status="warn",
            severity="medium",
            summary="Secret rotation has upcoming/manual items to review.",
            detail="; ".join(warnings[:10]),
            metadata={"warnings": warnings, "secrets": seen},
        )

    return CheckResult(
        name="secret_rotation",
        status="pass",
        severity="info",
        summary=f"Secret rotation ledger is healthy for {len(seen)} tracked secrets.",
        metadata={"secrets": seen},
    )


def _decode_jwt_payload(token: str) -> dict[str, object]:
    parts = token.split(".")
    if len(parts) < 2:
        raise ValueError("not a JWT")
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    return json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))


def _verify_jwt_exp(
    token: str,
    *,
    now: datetime | None = None,
    min_hours: float = JWT_VERIFY_MIN_HOURS,
) -> tuple[str, str]:
    now = now or datetime.now(UTC)
    try:
        payload = _decode_jwt_payload(token)
        exp = int(payload["exp"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return (
            "failed",
            f"JWT expiration could not be decoded: {exc.__class__.__name__}",
        )
    expires_at = datetime.fromtimestamp(exp, tz=UTC)
    hours_left = (expires_at - now).total_seconds() / 3600
    if hours_left <= 0:
        return "failed", "JWT is expired"
    if hours_left < min_hours:
        return "warning", f"JWT expires in {hours_left:.1f} hours"
    return "passed", f"JWT expires in {hours_left:.1f} hours"


def _remote_jwt_verify(
    node: str,
    secret_key: str,
    node_map: dict[str, dict[str, str]],
    *,
    min_hours: float = JWT_VERIFY_MIN_HOURS,
    ssh: Callable[[str, str], CommandResult] = run_ssh,
) -> tuple[str, str]:
    node_info = node_map.get(node)
    if not node_info:
        return "skipped", "node is not in SSH map"
    if not remote_ssh_probe_enabled():
        return "skipped", "remote SSH probe not configured"
    if secret_key not in REMOTE_JWT_ALLOWED_KEYS:
        return "skipped", f"remote JWT key {secret_key} is not allowlisted"
    command = f"porchlight jwt-exp {secret_key} {min_hours:g}"
    result = ssh(node_info["ssh_target"], command)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[:160]
        return "failed", f"remote JWT probe failed: {detail or 'ssh command failed'}"
    try:
        payload = json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        return "failed", "remote JWT probe returned invalid JSON"
    status = str(payload.get("status") or "failed")
    detail = str(payload.get("detail") or "")
    if status not in {"passed", "warning", "failed", "skipped"}:
        return "failed", "remote JWT probe returned invalid status"
    return status, detail


def _secret_value_for_probe(name: str, spec: dict[str, object]) -> str | None:
    key = str(spec.get("secret_key") or name)
    try:
        return get_secret(key).strip()
    except Exception:
        if key != name:
            try:
                return get_secret(name).strip()
            except Exception:
                return None
        return None


def _verify_cloudflare_api(
    command: Callable[..., CommandResult] = run_command,
) -> tuple[str, str]:
    token = _secret_or_env("CLOUDFLARE_API_TOKEN")
    if not token:
        return "failed", "Cloudflare API token is not configured"
    account_id = _cloudflare_account_id()
    path = (
        f"/accounts/{account_id}/tokens/verify" if account_id else "/user/tokens/verify"
    )
    result = command(
        [
            "curl",
            "-sS",
            "--max-time",
            "20",
            "-H",
            f"Authorization: Bearer {token}",
            f"{CLOUDFLARE_API_BASE.rstrip()}{path}",
        ],
        timeout=25,
    )
    if result.returncode != 0:
        return "failed", "Cloudflare token verify request failed"
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return "failed", "Cloudflare token verify returned invalid JSON"
    if payload.get("success") is True:
        return "passed", "Cloudflare token verified"
    return "failed", json.dumps(payload.get("errors") or payload)[:240]


def _verify_github_api(
    token: str | None,
    expect_login: str | None,
    command: Callable[..., CommandResult] = run_command,
) -> tuple[str, str]:
    if not token:
        return "failed", "GitHub token is not configured"
    result = command(
        [
            "curl",
            "-sS",
            "--max-time",
            "20",
            "-H",
            f"Authorization: token {token}",
            "https://api.github.com/user",
        ],
        timeout=25,
    )
    if result.returncode != 0:
        return "failed", "GitHub token probe failed"
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return "failed", "GitHub token probe returned invalid JSON"
    login = str(payload.get("login") or "")
    if expect_login and login != expect_login:
        return "failed", "GitHub token login did not match expected account"
    return "passed", "GitHub token verified"


def _verify_latest_gmail_health(
    psql: Callable[[str], CommandResult] = run_psql,
    now: datetime | None = None,
) -> tuple[str, str]:
    now = now or datetime.now(UTC)
    query = """
SELECT status,
       COALESCE(checked_at::text, ''),
       COALESCE(error_type, ''),
       COALESCE(error_subtype, '')
FROM public.alpha_gmail_oauth_health
ORDER BY checked_at DESC
LIMIT 1;
""".strip()
    result = psql(query)
    if result.returncode != 0:
        return "failed", "Could not read Gmail OAuth health ledger"
    rows = parse_psql_rows(result.stdout)
    if not rows:
        return "warning", "No Gmail OAuth health check has been recorded"
    status, checked_at, error_type, error_subtype = (rows[0] + ["", "", "", ""])[:4]
    checked = _parse_timestamp(checked_at)
    if checked is None:
        return "warning", "Latest Gmail OAuth health timestamp is invalid"
    age_hours = (now - checked).total_seconds() / 3600
    if status != "ok":
        detail = " ".join(part for part in (error_type, error_subtype) if part)
        return "failed", f"Gmail OAuth health is {status}: {detail}".strip()
    if age_hours > SECRET_VERIFY_MAX_AGE_HOURS:
        return "warning", f"Gmail OAuth health is stale ({age_hours:.1f} hours old)"
    return "passed", f"Gmail OAuth health ok ({age_hours:.1f} hours old)"


def _verify_health_url(
    spec: dict[str, object],
    *,
    command: Callable[..., CommandResult] = run_command,
) -> tuple[str, str]:
    restarts = spec.get("restarts")
    if not isinstance(restarts, list):
        return "skipped", "no health URL configured"
    urls = [
        str(item.get("health_url"))
        for item in restarts
        if isinstance(item, dict) and item.get("health_url")
    ]
    if not urls:
        return "skipped", "no health URL configured"
    failures = []
    for url in urls:
        result = command(
            [
                "curl",
                "-sk",
                "--max-time",
                "15",
                "-o",
                "/dev/null",
                "-w",
                "%{http_code}",
                url,
            ],
            timeout=20,
        )
        code = (result.stdout or "").strip()
        if result.returncode != 0 or not code.startswith(("2", "3")):
            failures.append(f"{url} HTTP {code or result.returncode}")
    if failures:
        return "failed", "; ".join(failures[:3])
    return "passed", f"{len(urls)} health URL(s) reachable"


def _verify_family_smoke_auth(
    spec: dict[str, object],
    pin: str,
    *,
    member_name: str = "smoke_test_parent",
    expected_role: str = "parent",
    command: Callable[..., CommandResult] = run_command,
) -> tuple[str, str]:
    restarts = spec.get("restarts")
    if not isinstance(restarts, list):
        return "skipped", "no Family smoke auth URL configured"
    health_url = next(
        (
            str(item.get("health_url"))
            for item in restarts
            if isinstance(item, dict) and item.get("health_url")
        ),
        "",
    )
    if not health_url.endswith("/health"):
        return "skipped", "Family smoke auth URL could not be derived"
    auth_url = health_url[: -len("/health")] + "/v1/auth/pin"
    result = command(
        [
            "curl",
            "-sk",
            "--max-time",
            "20",
            "-X",
            "POST",
            "-H",
            "Content-Type: application/json",
            "-d",
            json.dumps({"name": member_name, "pin": pin}),
            auth_url,
        ],
        timeout=25,
    )
    if result.returncode != 0:
        return "failed", "Family smoke auth request failed"
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return "failed", "Family smoke auth returned invalid JSON"
    if payload.get("token") and payload.get("role") == expected_role:
        return "passed", f"Family smoke auth passed for synthetic {expected_role}"
    return (
        "failed",
        f"Family smoke auth did not return a synthetic {expected_role} token",
    )


def _verify_secret_live(
    name: str,
    spec: dict[str, object],
    *,
    node_map: dict[str, dict[str, str]],
    psql: Callable[[str], CommandResult] = run_psql,
    command: Callable[..., CommandResult] = run_command,
    ssh: Callable[[str, str], CommandResult] = run_ssh,
) -> tuple[str, str]:
    verify = spec.get("verify") if isinstance(spec.get("verify"), dict) else {}
    verify_type = str(verify.get("type") or "none")
    if verify_type == "none":
        if spec.get("requires_alter_role"):
            return (
                "skipped",
                "manual DB credential rotation is ledger-tracked; no safe live probe configured",
            )
        return "skipped", "no live probe configured"
    if verify_type == "jwt_exp":
        nodes = spec.get("nodes") if isinstance(spec.get("nodes"), list) else []
        secret_key = str(spec.get("secret_key") or name)
        min_hours = float(verify.get("min_hours") or JWT_VERIFY_MIN_HOURS)
        local_node = current_node_name()
        if len(nodes) == 1 and nodes[0] != local_node:
            return _remote_jwt_verify(
                str(nodes[0]),
                secret_key,
                node_map,
                min_hours=min_hours,
                ssh=ssh,
            )
        token = _secret_value_for_probe(name, spec)
        if not token:
            return "failed", "JWT secret is not configured"
        return _verify_jwt_exp(token, min_hours=min_hours)
    if verify_type == "cloudflare_api":
        return _verify_cloudflare_api(command=command)
    if verify_type == "github_api":
        return _verify_github_api(
            _secret_value_for_probe(name, spec),
            str(verify.get("expect_login") or ""),
            command=command,
        )
    if verify_type == "gmail_oauth_health":
        return _verify_latest_gmail_health(psql=psql)
    if verify_type == "gateway_health":
        if not _secret_value_for_probe(name, spec):
            return "failed", "secret is not configured"
        return _verify_health_url(spec, command=command)
    if verify_type == "family_smoke":
        status, detail = _verify_health_url(spec, command=command)
        if status == "failed":
            return status, detail
        pin = _secret_value_for_probe(name, spec)
        if not pin:
            return (
                "warning",
                "Family smoke PIN is not available to Porchlight; API health is reachable",
            )
        return _verify_family_smoke_auth(spec, pin, command=command)
    if verify_type == "family_external_smoke":
        status, detail = _verify_health_url(spec, command=command)
        if status == "failed":
            return status, detail
        pin = _secret_value_for_probe(name, spec)
        if not pin:
            return (
                "warning",
                "Family external smoke PIN is not available to Porchlight; API health is reachable",
            )
        return _verify_family_smoke_auth(
            spec,
            pin,
            member_name="smoke_test_external",
            expected_role="external",
            command=command,
        )
    return "skipped", f"{verify_type} is side-effecting or not implemented"


def check_secret_live_verification(
    node_map: dict[str, dict[str, str]] | None = None,
    config_path: Path = SECRET_ROTATION_CONFIG,
    psql: Callable[[str], CommandResult] = run_psql,
    command: Callable[..., CommandResult] = run_command,
    ssh: Callable[[str, str], CommandResult] = run_ssh,
) -> CheckResult:
    node_map = node_map or load_json(NODE_MAP_PATH)
    config = load_json(config_path)
    configured = config.get("secrets", {})
    results: dict[str, dict[str, str]] = {}
    failed: list[str] = []
    warning: list[str] = []

    for name, raw_spec in configured.items():
        spec = raw_spec if isinstance(raw_spec, dict) else {}
        status, detail = _verify_secret_live(
            name,
            spec,
            node_map=node_map,
            psql=psql,
            command=command,
            ssh=ssh,
        )
        results[name] = {"status": status, "detail": detail}
        if status == "failed":
            failed.append(f"{name}: {detail}")
        elif status == "warning":
            warning.append(f"{name}: {detail}")

    verified_count = sum(1 for item in results.values() if item["status"] == "passed")
    skipped_count = sum(1 for item in results.values() if item["status"] == "skipped")
    if failed:
        return CheckResult(
            name="secret_live_verification",
            status="fail",
            severity="critical",
            summary="One or more managed secrets failed live verification.",
            detail="; ".join((failed + warning)[:10]),
            metadata={"results": results},
        )
    if warning:
        return CheckResult(
            name="secret_live_verification",
            status="warn",
            severity="medium",
            summary="One or more managed secrets need live-verification attention.",
            detail="; ".join(warning[:10]),
            metadata={"results": results},
        )
    return CheckResult(
        name="secret_live_verification",
        status="pass",
        severity="info",
        summary=(
            f"Live verification passed for {verified_count} managed secret(s); "
            f"{skipped_count} probe(s) are skipped by design."
        ),
        metadata={"results": results},
    )


def check_security_launchagents(
    node_map: dict[str, dict[str, str]] | None = None,
    ssh: Callable[[str, str], CommandResult] = run_ssh,
) -> CheckResult:
    node_map = node_map or load_json(NODE_MAP_PATH)
    local_node = current_node_name()
    remote_probe_enabled = remote_ssh_probe_enabled()
    missing_by_node: dict[str, list[str]] = {}
    unreachable: dict[str, str] = {}
    loaded_by_node: dict[str, list[str]] = {}
    skipped_remote: dict[str, str] = {}

    for node, expected in SECURITY_LAUNCHAGENTS.items():
        if node == local_node:
            result = run_command(["launchctl", "list"])
        else:
            if not remote_probe_enabled:
                skipped_remote[node] = "remote SSH probe not configured"
                continue
            target = node_map[node]["ssh_target"]
            result = ssh(target, "launchctl list")
        if result.returncode != 0:
            unreachable[node] = (result.stderr or result.stdout).strip()[:300]
            continue
        loaded = parse_launchctl_output(result.stdout)
        loaded_by_node[node] = sorted(label for label in loaded if label in expected)
        missing = sorted(expected - loaded)
        if missing:
            missing_by_node[node] = missing

    if unreachable or missing_by_node:
        parts = []
        for node, labels in missing_by_node.items():
            parts.append(f"{node} missing {', '.join(labels)}")
        for node in unreachable:
            parts.append(f"{node} unreachable")
        return CheckResult(
            name="security_launchagents",
            status="fail",
            severity="high",
            summary="One or more security LaunchAgents are not confirmed loaded.",
            detail="; ".join(parts),
            metadata={
                "missing_by_node": missing_by_node,
                "unreachable": unreachable,
                "loaded_by_node": loaded_by_node,
                "skipped_remote": skipped_remote,
            },
        )

    if skipped_remote:
        local_count = sum(len(labels) for labels in loaded_by_node.values())
        return CheckResult(
            name="security_launchagents",
            status="warn",
            severity="medium",
            summary="Local security LaunchAgents are loaded, but remote nodes were not probed.",
            detail="; ".join(f"{node}: {msg}" for node, msg in skipped_remote.items()),
            metadata={
                "loaded_by_node": loaded_by_node,
                "skipped_remote": skipped_remote,
                "local_loaded_count": local_count,
            },
        )

    total = sum(len(labels) for labels in SECURITY_LAUNCHAGENTS.values())
    return CheckResult(
        name="security_launchagents",
        status="pass",
        severity="info",
        summary=f"All {total} security LaunchAgents are loaded.",
        metadata={"loaded_by_node": loaded_by_node},
    )


def parse_json_log_lines(text: str) -> list[dict]:
    records = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            records.append(payload)
    return records


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_successful_rotation_record(record: dict) -> bool:
    message = str(record.get("message", "")).lower()
    return "rotation complete" in message or "rotation skipped" in message


def check_token_rotation_logs(
    node_map: dict[str, dict[str, str]] | None = None,
    ssh: Callable[[str, str], CommandResult] = run_ssh,
    now: datetime | None = None,
    max_age_hours: int = 36,
) -> CheckResult:
    node_map = node_map or load_json(NODE_MAP_PATH)
    local_node = current_node_name()
    remote_probe_enabled = remote_ssh_probe_enabled()
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(hours=max_age_hours)
    stale: dict[str, str] = {}
    recent: dict[str, str] = {}
    skipped_remote: dict[str, str] = {}

    for node, expected_log_nodes in TOKEN_LOG_NODES.items():
        if node == local_node:
            result = run_command(["/bin/sh", "-lc", TOKEN_LOG_COMMAND])
        else:
            if not remote_probe_enabled:
                skipped_remote[node] = "remote SSH probe not configured"
                continue
            target = node_map[node]["ssh_target"]
            result = ssh(target, TOKEN_LOG_COMMAND)
        if result.returncode != 0:
            stale[node] = "could not read token_rotation.log"
            continue
        records = parse_json_log_lines(result.stdout)
        for log_node in expected_log_nodes:
            candidates = [
                rec
                for rec in records
                if rec.get("node") == log_node and _is_successful_rotation_record(rec)
            ]
            latest = max(
                candidates,
                key=lambda rec: (
                    _parse_timestamp(rec.get("timestamp"))
                    or datetime.min.replace(tzinfo=UTC)
                ),
                default=None,
            )
            latest_ts = _parse_timestamp(latest.get("timestamp")) if latest else None
            if latest_ts and latest_ts >= cutoff:
                recent[log_node] = latest_ts.isoformat()
            else:
                stale[log_node] = (
                    "no successful rotation record within freshness window"
                )

    if stale:
        return CheckResult(
            name="token_rotation_logs",
            status="fail",
            severity="high",
            summary="Some service-token rotation logs are stale or missing.",
            detail="; ".join(f"{node}: {msg}" for node, msg in stale.items()),
            metadata={
                "stale": stale,
                "recent": recent,
                "skipped_remote": skipped_remote,
                "max_age_hours": max_age_hours,
            },
        )

    if skipped_remote:
        return CheckResult(
            name="token_rotation_logs",
            status="warn",
            severity="medium",
            summary="Local service-token logs are fresh, but remote nodes were not probed.",
            detail="; ".join(f"{node}: {msg}" for node, msg in skipped_remote.items()),
            metadata={
                "recent": recent,
                "skipped_remote": skipped_remote,
                "max_age_hours": max_age_hours,
            },
        )

    return CheckResult(
        name="token_rotation_logs",
        status="pass",
        severity="info",
        summary=f"All service-token rotators have a fresh success within {max_age_hours} hours.",
        metadata={"recent": recent, "max_age_hours": max_age_hours},
    )


RESTORE_DRILL_STATUS_COMMAND = "porchlight restore-drill-status"


def _hours_since(iso_ts: str, now: datetime) -> float | None:
    if not iso_ts:
        return None
    try:
        observed = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=UTC)
    return max(0.0, (now - observed.astimezone(UTC)).total_seconds() / 3600)


def check_backup_recovery(
    node_map: dict[str, dict[str, str]] | None = None,
    ssh: Callable[[str, str], CommandResult] = run_ssh,
    now: datetime | None = None,
    max_age_hours: int = RESTORE_DRILL_MAX_AGE_HOURS,
) -> CheckResult:
    node_map = node_map or load_json(NODE_MAP_PATH)
    sandbox = node_map.get("sandbox")
    target = sandbox.get("ssh_target") if isinstance(sandbox, dict) else None
    if not target:
        return CheckResult(
            name="backup_recovery",
            status="fail",
            severity="high",
            summary="Restore-drill monitor cannot find the Sandbox SSH target.",
            detail="scripts/node_ssh_map.json must include sandbox.ssh_target.",
            metadata={"max_age_hours": max_age_hours},
        )

    local_node = current_node_name()
    if not remote_ssh_probe_enabled() and local_node != "sandbox":
        return CheckResult(
            name="backup_recovery",
            status="warn",
            severity="medium",
            summary="Restore-drill monitor cannot remotely inspect Sandbox.",
            detail="Configure PORCHLIGHT_SSH_KEY or PORCHLIGHT_REMOTE_SSH_ENABLED.",
            metadata={
                "target_node": "sandbox",
                "max_age_hours": max_age_hours,
                "skipped_remote": {"sandbox": "remote SSH probe not configured"},
            },
        )

    result = (
        run_command(
            [str(SCRIPT_DIR / "porchlight_ssh_probe.sh")],
            timeout=20,
            env={**os.environ, "SSH_ORIGINAL_COMMAND": RESTORE_DRILL_STATUS_COMMAND},
        )
        if local_node == "sandbox"
        else ssh(target, RESTORE_DRILL_STATUS_COMMAND)
    )
    if result.returncode != 0:
        return CheckResult(
            name="backup_recovery",
            status="fail",
            severity="high",
            summary="Restore-drill monitor could not inspect Sandbox recovery reports.",
            detail=(result.stderr or result.stdout).strip()[:500],
            metadata={"target_node": "sandbox", "max_age_hours": max_age_hours},
        )

    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return CheckResult(
            name="backup_recovery",
            status="fail",
            severity="high",
            summary="Restore-drill monitor returned invalid JSON.",
            detail=(result.stdout or result.stderr).strip()[:500],
            metadata={"target_node": "sandbox", "max_age_hours": max_age_hours},
        )
    if not isinstance(payload, dict) or payload.get("status") == "unavailable":
        return CheckResult(
            name="backup_recovery",
            status="fail",
            severity="high",
            summary="No restore-drill report is available on Sandbox.",
            detail=str(payload.get("reason") or "restore drill report missing"),
            metadata={"target_node": "sandbox", "max_age_hours": max_age_hours},
        )

    checked_at = now or datetime.now(UTC)
    age_hours = _hours_since(str(payload.get("report_mtime") or ""), checked_at)
    notification = payload.get("notification")
    notify_event = (
        str(notification.get("event") or "")
        if isinstance(notification, dict)
        else "unknown"
    )
    metadata = {
        "target_node": "sandbox",
        "max_age_hours": max_age_hours,
        "age_hours": round(age_hours, 2) if age_hours is not None else None,
        **payload,
    }
    report_status = str(payload.get("status") or "unknown")
    source_dump = str(payload.get("source_dump") or "unknown dump")
    run_id = str(payload.get("run_id") or "unknown run")

    if report_status != "pass":
        return CheckResult(
            name="backup_recovery",
            status="fail",
            severity="critical",
            summary="Latest restore drill did not pass.",
            detail=str(
                payload.get("fail_reasons") or f"run {run_id} status {report_status}"
            ),
            metadata=metadata,
        )
    if age_hours is None:
        return CheckResult(
            name="backup_recovery",
            status="warn",
            severity="medium",
            summary="Latest restore drill passed, but its age could not be determined.",
            detail=f"Run {run_id} restored {source_dump}.",
            metadata=metadata,
        )
    if age_hours > max_age_hours:
        return CheckResult(
            name="backup_recovery",
            status="fail",
            severity="high",
            summary="Latest restore drill is stale.",
            detail=(
                f"Run {run_id} is {age_hours:.1f}h old; target is <= {max_age_hours}h."
            ),
            metadata=metadata,
        )
    if notify_event != "mm_notify_sent":
        return CheckResult(
            name="backup_recovery",
            status="warn",
            severity="medium",
            summary="Latest restore drill passed, but notification proof is missing.",
            detail=(
                f"Run {run_id} restored {source_dump}; "
                f"notification event: {notify_event or 'unknown'}."
            ),
            metadata=metadata,
        )

    return CheckResult(
        name="backup_recovery",
        status="pass",
        severity="info",
        summary=f"Latest restore drill passed {age_hours:.1f}h ago.",
        detail=f"Run {run_id} restored {source_dump}; Mattermost notification sent.",
        metadata=metadata,
    )


def _parse_http_headers(text: str) -> tuple[int | None, dict[str, str]]:
    status: int | None = None
    headers: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.upper().startswith("HTTP/"):
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                status = int(parts[1])
            headers = {}
            continue
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()
    return status, headers


def check_cloudflare_access(
    url: str = CLOUDFLARE_ACCESS_URL,
    command: Callable[..., CommandResult] = run_command,
) -> CheckResult:
    result = command(
        [
            "curl",
            "-sS",
            "-I",
            "--max-time",
            "15",
            url,
        ],
        timeout=20,
    )
    if result.returncode != 0:
        return CheckResult(
            name="cloudflare_access",
            status="fail",
            severity="high",
            summary=f"Could not reach {url}.",
            detail=(result.stderr or result.stdout).strip()[:500],
        )

    status, headers = _parse_http_headers(result.stdout)
    location = headers.get("location", "")
    authenticate = headers.get("www-authenticate", "")
    gated = status in (301, 302, 303, 307, 308, 401, 403) and (
        "cloudflareaccess.com" in location or "Cloudflare-Access" in authenticate
    )
    if not gated:
        return CheckResult(
            name="cloudflare_access",
            status="fail",
            severity="critical",
            summary=f"{url} did not look protected by Cloudflare Access.",
            detail=f"status={status} location={location[:160]} www-authenticate={authenticate[:160]}",
            metadata={"status": status, "location": location},
        )
    return CheckResult(
        name="cloudflare_access",
        status="pass",
        severity="info",
        summary=f"{url} is gated by Cloudflare Access before origin.",
        metadata={"status": status},
    )


def _secret_or_env(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    if value:
        return value
    try:
        return get_secret(name).strip()
    except Exception:
        return None


def _cloudflare_expected_hosts() -> list[str]:
    configured = os.getenv("PORCHLIGHT_CLOUDFLARE_EXPECTED_HOSTS", "").strip()
    if configured:
        hosts = [item.strip().lower() for item in configured.split(",")]
        return sorted({host for host in hosts if host})
    host = urlparse(CLOUDFLARE_ACCESS_URL).hostname
    return [host.lower()] if host else []


def _cloudflare_expected_actors() -> set[str]:
    configured = os.getenv("PORCHLIGHT_CLOUDFLARE_EXPECTED_ACTORS", "").strip()
    if configured:
        return {item.strip().lower() for item in configured.split(",") if item.strip()}
    return set(DEFAULT_CLOUDFLARE_EXPECTED_ACTORS)


def _csv_config_set(name: str) -> set[str]:
    configured = _secret_or_env(name) or ""
    configured = configured.strip()
    if not configured:
        return set()
    return {item.strip().lower() for item in configured.split(",") if item.strip()}


def _cloudflare_expected_policy_emails() -> set[str]:
    return _csv_config_set("PORCHLIGHT_CLOUDFLARE_EXPECTED_POLICY_EMAILS")


def _cloudflare_allowed_public_hosts() -> set[str]:
    return _csv_config_set("PORCHLIGHT_CLOUDFLARE_ALLOWED_PUBLIC_HOSTS")


def _normalize_cloudflare_target(
    value: str, *, include_path: bool = False
) -> str | None:
    raw = value.strip().lower()
    if not raw:
        return None
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    host = parsed.hostname or ""
    if "." not in host:
        return None
    if not include_path:
        return host
    path = (parsed.path or "").strip("/")
    return f"{host}/{path}" if path else host


def _cloudflare_allowed_public_paths() -> set[str]:
    targets: set[str] = set()
    for item in _csv_config_set("PORCHLIGHT_CLOUDFLARE_ALLOWED_PUBLIC_PATHS"):
        normalized = _normalize_cloudflare_target(item, include_path=True)
        if normalized:
            targets.add(normalized)
    return targets


def _cloudflare_forbidden_host_patterns() -> tuple[str, ...]:
    configured = os.getenv("PORCHLIGHT_CLOUDFLARE_FORBIDDEN_HOST_PATTERNS", "").strip()
    if configured:
        return tuple(
            item.strip().lower() for item in configured.split(",") if item.strip()
        )
    return DEFAULT_CLOUDFLARE_FORBIDDEN_HOST_PATTERNS


def _cloudflare_forbidden_app_terms() -> tuple[str, ...]:
    configured = os.getenv("PORCHLIGHT_CLOUDFLARE_FORBIDDEN_APP_TERMS", "").strip()
    if configured:
        return tuple(
            item.strip().lower() for item in configured.split(",") if item.strip()
        )
    return DEFAULT_CLOUDFLARE_FORBIDDEN_APP_TERMS


def _cloudflare_api_get(
    path: str,
    *,
    params: dict[str, str] | None = None,
    command: Callable[..., CommandResult] = run_command,
) -> tuple[int, dict]:
    token = _secret_or_env("CLOUDFLARE_API_TOKEN")
    if not token:
        return 0, {"success": False, "errors": [{"message": "missing_token"}]}
    query = f"?{urlencode(params)}" if params else ""
    result = command(
        [
            "curl",
            "-sS",
            "--max-time",
            "20",
            "-H",
            f"Authorization: Bearer {token}",
            f"{CLOUDFLARE_API_BASE.rstrip('/')}{path}{query}",
        ],
        timeout=25,
    )
    if result.returncode != 0:
        return result.returncode, {
            "success": False,
            "errors": [{"message": (result.stderr or result.stdout).strip()[:500]}],
        }
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return 1, {"success": False, "errors": [{"message": "invalid_json"}]}
    return 0, payload if isinstance(payload, dict) else {"success": False}


def _cloudflare_account_id() -> str | None:
    return _secret_or_env("CLOUDFLARE_ACCOUNT_ID")


def _app_target_values(app: dict) -> list[str]:
    values: list[str] = []
    for key in ("domain", "aud", "hostname"):
        value = app.get(key)
        if isinstance(value, str) and value:
            values.append(value)
    for nested_key in ("domains", "self_hosted_domains"):
        value = app.get(nested_key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item:
                    values.append(item)
    destinations = app.get("destinations")
    if isinstance(destinations, list):
        for destination in destinations:
            if not isinstance(destination, dict):
                continue
            uri = destination.get("uri")
            if isinstance(uri, str) and uri:
                values.append(uri)
    return values


def _app_hostnames(app: dict) -> set[str]:
    hosts = set()
    for value in _app_target_values(app):
        host = _normalize_cloudflare_target(value)
        if host:
            hosts.add(host)
    return hosts


def _app_path_targets(app: dict) -> set[str]:
    targets = set()
    for value in _app_target_values(app):
        target = _normalize_cloudflare_target(value, include_path=True)
        if target:
            targets.add(target)
    return targets


def _app_is_allowed_public_path(app: dict) -> bool:
    allowed_paths = _cloudflare_allowed_public_paths()
    if not allowed_paths:
        return False
    targets = _app_path_targets(app)
    return bool(targets) and targets <= allowed_paths


def _policy_has_everyone_rule(policy: dict) -> bool:
    for rule_key in ("include", "exclude", "require"):
        rules = policy.get(rule_key)
        if not isinstance(rules, list):
            continue
        for rule in rules:
            if isinstance(rule, dict) and "everyone" in rule:
                return True
    return False


def _policy_broad_rule_details(policy: dict) -> list[str]:
    details: list[str] = []
    for rule_key in ("include", "exclude", "require"):
        rules = policy.get(rule_key)
        if not isinstance(rules, list):
            continue
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            if "email_domain" in rule:
                details.append(f"{rule_key}: email_domain")
            if "everyone" in rule:
                details.append(f"{rule_key}: everyone")
            if "common_name" in rule:
                details.append(f"{rule_key}: common_name")
    return details


def _policy_email_values(policy: dict) -> set[str]:
    emails: set[str] = set()
    for rule_key in ("include", "require"):
        rules = policy.get(rule_key)
        if not isinstance(rules, list):
            continue
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            email_rule = rule.get("email")
            if isinstance(email_rule, dict):
                email = email_rule.get("email")
                if isinstance(email, str) and email.strip():
                    emails.add(email.strip().lower())
            if isinstance(email_rule, str) and email_rule.strip():
                emails.add(email_rule.strip().lower())
            emails_rule = rule.get("emails")
            if isinstance(emails_rule, list):
                emails.update(
                    item.strip().lower()
                    for item in emails_rule
                    if isinstance(item, str) and item.strip()
                )
    return emails


def _forbidden_cloudflare_apps(apps: list[dict]) -> list[str]:
    allowed_hosts = _cloudflare_allowed_public_hosts()
    host_patterns = _cloudflare_forbidden_host_patterns()
    app_terms = _cloudflare_forbidden_app_terms()
    forbidden: list[str] = []
    for app in apps:
        if not isinstance(app, dict):
            continue
        name = str(app.get("name") or app.get("id") or "unknown")
        name_lc = name.lower()
        hostnames = _app_hostnames(app)
        blocked_hosts = [
            host
            for host in sorted(hostnames)
            if host not in allowed_hosts
            and any(fnmatch(host, pattern) for pattern in host_patterns)
        ]
        term_hit = next((term for term in app_terms if term in name_lc), None)
        if blocked_hosts:
            forbidden.append(f"{name}: {', '.join(blocked_hosts)}")
        elif term_hit and not (hostnames and hostnames <= allowed_hosts):
            forbidden.append(f"{name}: app name contains {term_hit!r}")
    return forbidden


def check_cloudflare_access_policy_drift(
    command: Callable[..., CommandResult] = run_command,
) -> CheckResult:
    account_id = _cloudflare_account_id()
    expected_hosts = _cloudflare_expected_hosts()
    if not account_id or not _secret_or_env("CLOUDFLARE_API_TOKEN"):
        return CheckResult(
            name="cloudflare_access_policy_drift",
            status="warn",
            severity="medium",
            summary="Cloudflare API credentials are not configured for Access policy monitoring.",
            detail="Set CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN on Brain secrets.",
            metadata={"expected_hosts": expected_hosts},
        )

    rc, payload = _cloudflare_api_get(
        f"/accounts/{account_id}/access/apps",
        command=command,
    )
    if rc != 0 or payload.get("success") is not True:
        return CheckResult(
            name="cloudflare_access_policy_drift",
            status="fail",
            severity="high",
            summary="Could not list Cloudflare Access applications.",
            detail=json.dumps(payload.get("errors") or payload)[:500],
            metadata={"expected_hosts": expected_hosts},
        )

    apps = payload.get("result") if isinstance(payload.get("result"), list) else []
    forbidden_apps = _forbidden_cloudflare_apps(apps)
    if forbidden_apps:
        return CheckResult(
            name="cloudflare_access_policy_drift",
            status="fail",
            severity="critical",
            summary="Forbidden Alpha/Brain-style Cloudflare Access app exposure detected.",
            detail=", ".join(forbidden_apps[:8]),
            metadata={
                "expected_hosts": expected_hosts,
                "forbidden_apps": forbidden_apps,
                "allowed_public_hosts": sorted(_cloudflare_allowed_public_hosts()),
            },
        )

    matched = []
    public_path_exceptions = []
    risky_policies: list[str] = []
    no_policy_apps: list[str] = []
    expected_policy_emails = _cloudflare_expected_policy_emails()
    matched_policy_emails: set[str] = set()
    for app in apps:
        if not isinstance(app, dict):
            continue
        hostnames = _app_hostnames(app)
        if expected_hosts and not (hostnames & set(expected_hosts)):
            continue
        app_id = str(app.get("id") or "")
        name = str(app.get("name") or app_id or "unknown")
        path_targets = _app_path_targets(app)
        app_metadata = {
            "id": app_id,
            "name": name,
            "hostnames": sorted(hostnames),
            "path_targets": sorted(path_targets),
        }
        if _app_is_allowed_public_path(app):
            public_path_exceptions.append(app_metadata)
            continue
        matched.append(app_metadata)
        policies = app.get("policies")
        if not isinstance(policies, list) and app_id:
            _rc, policy_payload = _cloudflare_api_get(
                f"/accounts/{account_id}/access/apps/{app_id}/policies",
                command=command,
            )
            policies = (
                policy_payload.get("result")
                if isinstance(policy_payload.get("result"), list)
                else []
            )
        if not policies:
            no_policy_apps.append(name)
            continue
        for policy in policies:
            if not isinstance(policy, dict):
                continue
            matched_policy_emails.update(_policy_email_values(policy))
            action = str(policy.get("decision") or policy.get("action") or "").lower()
            policy_name = str(policy.get("name") or policy.get("id") or "unknown")
            if action == "bypass":
                risky_policies.append(f"{name}.{policy_name}: bypass")
            for detail in _policy_broad_rule_details(policy):
                risky_policies.append(f"{name}.{policy_name}: {detail}")

    if expected_hosts and not matched:
        return CheckResult(
            name="cloudflare_access_policy_drift",
            status="fail",
            severity="critical",
            summary="No protected Cloudflare Access application matched the expected hostnames.",
            detail=", ".join(expected_hosts),
            metadata={
                "expected_hosts": expected_hosts,
                "apps_seen": len(apps),
                "allowed_public_path_exceptions": public_path_exceptions,
            },
        )
    if risky_policies or no_policy_apps:
        details = []
        if risky_policies:
            details.append("risky policies: " + ", ".join(risky_policies[:8]))
        if no_policy_apps:
            details.append("apps without policies: " + ", ".join(no_policy_apps[:8]))
        return CheckResult(
            name="cloudflare_access_policy_drift",
            status="fail",
            severity="critical",
            summary="Cloudflare Access policy drift needs review.",
            detail="; ".join(details),
            metadata={
                "expected_hosts": expected_hosts,
                "matched": matched,
                "allowed_public_path_exceptions": public_path_exceptions,
                "risky_policies": risky_policies,
                "no_policy_apps": no_policy_apps,
            },
        )
    if expected_policy_emails:
        missing = sorted(expected_policy_emails - matched_policy_emails)
        unexpected = sorted(matched_policy_emails - expected_policy_emails)
        if missing or unexpected:
            details = []
            if missing:
                details.append("missing expected email(s): " + ", ".join(missing[:8]))
            if unexpected:
                details.append("unexpected email(s): " + ", ".join(unexpected[:8]))
            return CheckResult(
                name="cloudflare_access_policy_drift",
                status="fail",
                severity="critical",
                summary="Cloudflare Access policy membership drift needs review.",
                detail="; ".join(details),
                metadata={
                    "expected_hosts": expected_hosts,
                    "matched": matched,
                    "allowed_public_path_exceptions": public_path_exceptions,
                    "expected_policy_emails_count": len(expected_policy_emails),
                    "matched_policy_emails_count": len(matched_policy_emails),
                    "missing_policy_emails": missing,
                    "unexpected_policy_emails": unexpected,
                },
            )
    elif matched_policy_emails:
        return CheckResult(
            name="cloudflare_access_policy_drift",
            status="warn",
            severity="medium",
            summary="Cloudflare Access exact policy membership is not configured.",
            detail=(
                "Set PORCHLIGHT_CLOUDFLARE_EXPECTED_POLICY_EMAILS so Porchlight "
                "can detect unexpected family/external access drift."
            ),
            metadata={
                "expected_hosts": expected_hosts,
                "matched": matched,
                "allowed_public_path_exceptions": public_path_exceptions,
                "expected_policy_emails_count": 0,
                "matched_policy_emails_count": len(matched_policy_emails),
            },
        )

    return CheckResult(
        name="cloudflare_access_policy_drift",
        status="pass",
        severity="info",
        summary=f"Cloudflare Access policy shape is safe for {len(matched)} protected app(s).",
        metadata={
            "expected_hosts": expected_hosts,
            "matched": matched,
            "allowed_public_path_exceptions": public_path_exceptions,
            "expected_policy_emails_count": len(expected_policy_emails),
            "matched_policy_emails_count": len(matched_policy_emails),
        },
    )


def check_cloudflare_audit_logs(
    command: Callable[..., CommandResult] = run_command,
    now: datetime | None = None,
    window_hours: int = 24,
) -> CheckResult:
    account_id = _cloudflare_account_id()
    if not account_id or not _secret_or_env("CLOUDFLARE_API_TOKEN"):
        return CheckResult(
            name="cloudflare_audit_logs",
            status="warn",
            severity="medium",
            summary="Cloudflare audit-log monitoring is not configured.",
            detail="Set CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN on Brain secrets.",
        )

    now = now or datetime.now(UTC)
    since = (now - timedelta(hours=window_hours)).isoformat().replace("+00:00", "Z")
    before = now.isoformat().replace("+00:00", "Z")
    rc, payload = _cloudflare_api_get(
        f"/accounts/{account_id}/logs/audit",
        params={"since": since, "before": before, "per_page": "100"},
        command=command,
    )
    if rc != 0 or payload.get("success") is not True:
        return CheckResult(
            name="cloudflare_audit_logs",
            status="fail",
            severity="high",
            summary="Could not retrieve Cloudflare account audit logs.",
            detail=json.dumps(payload.get("errors") or payload)[:500],
        )

    logs = payload.get("result") if isinstance(payload.get("result"), list) else []
    access_related: list[dict[str, str]] = []
    expected_changes: list[dict[str, str]] = []
    unexpected_changes: list[str] = []
    failures: list[str] = []
    expected_actors = _cloudflare_expected_actors()
    for entry in logs:
        if not isinstance(entry, dict):
            continue
        haystack = json.dumps(entry, sort_keys=True, default=str).lower()
        if not any(term in haystack for term in ("access", "zero trust", "tunnel")):
            continue
        action = entry.get("action") if isinstance(entry.get("action"), dict) else {}
        actor = entry.get("actor") if isinstance(entry.get("actor"), dict) else {}
        resource = (
            entry.get("resource") if isinstance(entry.get("resource"), dict) else {}
        )
        item = {
            "when": str(entry.get("when") or ""),
            "actor": str(actor.get("email") or actor.get("id") or "unknown"),
            "action": str(action.get("type") or "unknown"),
            "result": str(action.get("result")),
            "resource": str(resource.get("type") or resource.get("id") or "unknown"),
        }
        access_related.append(item)
        if action.get("result") is False:
            failures.append(f"{item['when']} {item['actor']} {item['action']}")
            continue
        if item["actor"].lower() in expected_actors:
            expected_changes.append(item)
        else:
            unexpected_changes.append(
                f"{item['when']} {item['actor']} {item['action']}"
            )

    if failures:
        return CheckResult(
            name="cloudflare_audit_logs",
            status="fail",
            severity="high",
            summary="Cloudflare Access/Zero Trust audit logs contain failed control-plane actions.",
            detail="; ".join(failures[:8]),
            metadata={"window_hours": window_hours, "events": access_related[:20]},
        )
    if unexpected_changes:
        return CheckResult(
            name="cloudflare_audit_logs",
            status="warn",
            severity="medium",
            summary="Unexpected Cloudflare Access/Zero Trust changes occurred within the audit window.",
            detail="; ".join(unexpected_changes[:8]),
            metadata={
                "window_hours": window_hours,
                "events": access_related[:20],
                "expected_actors": sorted(expected_actors),
            },
        )
    if expected_changes:
        return CheckResult(
            name="cloudflare_audit_logs",
            status="pass",
            severity="info",
            summary="Only expected Cloudflare Access/Zero Trust changes occurred within the audit window.",
            detail="; ".join(
                f"{item['when']} {item['actor']} {item['action']}"
                for item in expected_changes[:8]
            ),
            metadata={
                "window_hours": window_hours,
                "events": access_related[:20],
                "expected_actors": sorted(expected_actors),
            },
        )

    return CheckResult(
        name="cloudflare_audit_logs",
        status="pass",
        severity="info",
        summary=f"No Cloudflare Access/Zero Trust audit-log changes in {window_hours} hours.",
        metadata={"window_hours": window_hours, "events_checked": len(logs)},
    )


def _severity_counts() -> dict[str, int]:
    return {"critical": 0, "high": 0, "medium": 0, "low": 0, "unknown": 0}


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        pass
    try:
        return "../" + str(path.relative_to(REPO_ROOT.parent))
    except ValueError:
        return str(path)


def _default_malware_scan_raw_paths(repo_root: Path) -> list[str]:
    raw_paths = list(MALWARE_SCAN_DEFAULT_PATHS)
    for repo_name in MALWARE_SCAN_SIBLING_REPOS:
        sibling = repo_root.parent / repo_name
        if sibling.exists() and sibling.resolve() != repo_root.resolve():
            raw_paths.append(str(sibling))
    return raw_paths


def _missing_default_malware_sibling_repos(repo_root: Path) -> list[str]:
    return [
        repo_name
        for repo_name in MALWARE_SCAN_SIBLING_REPOS
        if not (repo_root.parent / repo_name).exists()
    ]


def _malware_sibling_repo_paths(repo_root: Path) -> list[Path]:
    return [
        repo_root.parent / repo_name
        for repo_name in MALWARE_SCAN_SIBLING_REPOS
        if (repo_root.parent / repo_name).exists()
    ]


def _git_command_args(repo: Path, *git_args: str, token: str = "") -> list[str]:
    args = ["git"]
    if token:
        auth = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        args.extend(["-c", f"http.extraHeader=Authorization: Basic {auth}"])
    args.extend(["-C", str(repo), *git_args])
    return args


def _redact_command_output(value: str, token: str = "") -> str:
    redacted = value
    if token:
        redacted = redacted.replace(token, "<redacted>")
    return redacted.strip()[:500]


def check_malware_scan_repo_freshness(
    repo_root: Path = REPO_ROOT,
    command: Callable[..., CommandResult] = run_command,
) -> CheckResult:
    refreshed: list[dict[str, object]] = []
    failed: list[str] = []
    not_git: list[str] = []
    missing = _missing_default_malware_sibling_repos(repo_root)
    token = _secret_or_env("GITHUB_TOKEN") or ""

    for repo in _malware_sibling_repo_paths(repo_root):
        display = _display_path(repo)
        if not (repo / ".git").exists():
            not_git.append(display)
            continue
        before = command(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"])
        before_sha = before.stdout.strip() if before.returncode == 0 else "unknown"
        fetch = command(
            _git_command_args(
                repo,
                "fetch",
                "--prune",
                "--quiet",
                "origin",
                token=token,
            ),
            timeout=120,
        )
        if fetch.returncode != 0:
            detail = _redact_command_output(fetch.stderr or fetch.stdout, token)
            failed.append(f"{display}: fetch failed: {detail}")
            continue
        pull = command(
            _git_command_args(repo, "pull", "--ff-only", "--quiet", token=token),
            timeout=120,
        )
        if pull.returncode != 0:
            detail = _redact_command_output(pull.stderr or pull.stdout, token)
            failed.append(f"{display}: pull --ff-only failed: {detail}")
            continue
        after = command(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"])
        after_sha = after.stdout.strip() if after.returncode == 0 else "unknown"
        refreshed.append(
            {
                "repo": display,
                "before": before_sha,
                "after": after_sha,
                "changed": before_sha != after_sha,
            }
        )

    metadata = {
        "refreshed": refreshed,
        "failed": failed,
        "not_git": not_git,
        "missing_default_sibling_repos": missing,
    }
    if failed:
        return CheckResult(
            name="malware_scan_repo_freshness",
            status="fail",
            severity="high",
            summary="One or more malware-scan repos could not be refreshed before scanning.",
            detail="; ".join(failed[:8]),
            metadata=metadata,
        )
    if not_git:
        return CheckResult(
            name="malware_scan_repo_freshness",
            status="warn",
            severity="medium",
            summary="Some malware-scan roots are not git checkouts and cannot be refreshed.",
            detail=", ".join(not_git[:8]),
            metadata=metadata,
        )
    return CheckResult(
        name="malware_scan_repo_freshness",
        status="pass",
        severity="info",
        summary=f"Refreshed {len(refreshed)} sibling repo(s) before malware scan.",
        metadata=metadata,
    )


def _malware_scan_paths(repo_root: Path) -> list[Path]:
    configured = os.getenv("PORCHLIGHT_MALWARE_SCAN_PATHS", "").strip()
    raw_paths = (
        [item.strip() for item in configured.split(",") if item.strip()]
        if configured
        else _default_malware_scan_raw_paths(repo_root)
    )
    paths: list[Path] = []
    for raw_path in raw_paths:
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = repo_root / path
        if path.exists():
            paths.append(path)
    return paths


def _malware_scan_allowlist() -> set[str]:
    configured = _secret_or_env("PORCHLIGHT_MALWARE_SCAN_ALLOWLIST") or ""
    configured_entries = {
        item.strip().lower() for item in configured.split(",") if item.strip()
    }
    return set(MALWARE_SCAN_DEFAULT_ALLOWLIST) | configured_entries


def _should_scan_code_file(path: Path) -> bool:
    if any(part in MALWARE_SCAN_EXCLUDED_PARTS for part in path.parts):
        return False
    if path.is_dir():
        return False
    if path.suffix.lower() in MALWARE_SCAN_SUFFIXES:
        return True
    return path.name in {".envrc", "Dockerfile", "Makefile"}


def _iter_malware_scan_files(repo_root: Path) -> tuple[list[Path], int, list[Path]]:
    files: list[Path] = []
    skipped_large = 0
    roots = _malware_scan_paths(repo_root)
    for root in roots:
        candidates = root.rglob("*") if root.is_dir() else [root]
        for candidate in candidates:
            if not _should_scan_code_file(candidate):
                continue
            try:
                size = candidate.stat().st_size
            except OSError:
                continue
            if size > MALWARE_SCAN_MAX_FILE_BYTES:
                skipped_large += 1
                continue
            files.append(candidate)
    return sorted(set(files)), skipped_large, roots


def _line_number_for_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, max(0, offset)) + 1


def _malware_finding_allowed(
    *,
    display_path: str,
    rule_id: str,
    allowlist: set[str],
) -> bool:
    normalized_path = display_path.lower()
    normalized_rule = rule_id.lower()
    return (
        normalized_rule in allowlist
        or f"{normalized_path}:{normalized_rule}" in allowlist
    )


def _benign_sensitive_instruction_context(text: str, match: re.Match[str]) -> bool:
    before = text[max(0, match.start() - 80) : match.start()].lower()
    matched = match.group(0).lower()
    guardrail_phrases = (
        "do not",
        "don't",
        "never",
        "must not",
        "should not",
        "cannot",
        "refuse",
        "reject",
        "avoid",
        "block",
        "prevent",
    )
    if any(phrase in before[-60:] for phrase in guardrail_phrases):
        return True
    return any(
        f"{phrase} reveal" in matched
        or f"{phrase} print" in matched
        or f"{phrase} return" in matched
        or f"{phrase} share" in matched
        or f"{phrase} send" in matched
        or f"{phrase} dump" in matched
        for phrase in guardrail_phrases
    )


def _rule_applies_to_path(rule_id: str, path: Path) -> bool:
    if path.suffix.lower() in {".md", ".mdx"}:
        return rule_id == "sensitive_data_request_instruction"
    return True


def check_code_malware_scan(repo_root: Path = REPO_ROOT) -> CheckResult:
    """Static tripwire for code patterns commonly used by malware implants."""
    files, skipped_large, scan_roots = _iter_malware_scan_files(repo_root)
    allowlist = _malware_scan_allowlist()
    findings: list[dict[str, object]] = []
    unreadable: list[str] = []

    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            unreadable.append(_display_path(path))
            continue
        display_path = _display_path(path)
        for pattern in MALWARE_STATIC_PATTERNS:
            rule_id = str(pattern["id"])
            if not _rule_applies_to_path(rule_id, path):
                continue
            if rule_id == "macos_persistence_writer" and path.suffix == ".plist":
                continue
            if _malware_finding_allowed(
                display_path=display_path,
                rule_id=rule_id,
                allowlist=allowlist,
            ):
                continue
            regex = pattern["regex"]
            assert isinstance(regex, re.Pattern)
            for match in regex.finditer(text):
                if rule_id == "sensitive_data_request_instruction" and (
                    _benign_sensitive_instruction_context(text, match)
                ):
                    continue
                findings.append(
                    {
                        "path": display_path,
                        "line": _line_number_for_offset(text, match.start()),
                        "rule_id": rule_id,
                        "severity": pattern["severity"],
                        "summary": pattern["summary"],
                    }
                )

    severity = "info"
    status = "pass"
    if any(item["severity"] == "critical" for item in findings):
        status = "fail"
        severity = "critical"
    elif findings:
        status = "warn"
        severity = "high"
    elif unreadable:
        status = "warn"
        severity = "low"

    metadata = {
        "scan_roots": [_display_path(path) for path in scan_roots],
        "missing_default_sibling_repos": _missing_default_malware_sibling_repos(
            repo_root
        ),
        "files_scanned": len(files),
        "skipped_large_files": skipped_large,
        "unreadable_files": unreadable[:20],
        "findings": findings[:50],
        "finding_count": len(findings),
        "allowlist_count": len(allowlist),
    }
    if status == "fail":
        detail = "; ".join(
            f"{item['path']}:{item['line']} {item['rule_id']}" for item in findings[:8]
        )
        return CheckResult(
            name="code_malware_scan",
            status="fail",
            severity="critical",
            summary="Suspicious malware-style code patterns need review.",
            detail=detail,
            metadata=metadata,
        )
    if status == "warn":
        detail = "; ".join(
            f"{item['path']}:{item['line']} {item['rule_id']}" for item in findings[:8]
        )
        if unreadable and not detail:
            detail = "Unreadable files: " + ", ".join(unreadable[:8])
        return CheckResult(
            name="code_malware_scan",
            status="warn",
            severity=severity,
            summary="Code malware scan found items that need review.",
            detail=detail,
            metadata=metadata,
        )
    return CheckResult(
        name="code_malware_scan",
        status="pass",
        severity="info",
        summary="Static malware tripwire found no suspicious code patterns.",
        metadata=metadata,
    )


def _csv_env(name: str) -> list[str]:
    configured = os.getenv(name, "").strip()
    if not configured:
        return []
    return [item.strip() for item in configured.split(",") if item.strip()]


def _secret_leak_log_roots(repo_root: Path = REPO_ROOT) -> list[Path]:
    raw_paths = _csv_env("PORCHLIGHT_SECRET_LEAK_LOG_PATHS") or list(
        SECRET_LEAK_LOG_DEFAULT_PATHS
    )
    roots: list[Path] = []
    for raw_path in raw_paths:
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = repo_root / path
        if path.exists():
            roots.append(path)
    return roots


def _should_scan_secret_log(path: Path) -> bool:
    if any(part in SECRET_LEAK_EXCLUDED_PARTS for part in path.parts):
        return False
    if path.is_dir():
        return False
    return path.suffix.lower() in SECRET_LEAK_LOG_SUFFIXES


def _iter_secret_log_files(repo_root: Path = REPO_ROOT) -> list[Path]:
    files: list[Path] = []
    for root in _secret_leak_log_roots(repo_root):
        candidates = root.rglob("*") if root.is_dir() else [root]
        for candidate in candidates:
            if _should_scan_secret_log(candidate):
                files.append(candidate)
    return sorted(set(files))


def _read_tail_text(path: Path, max_bytes: int) -> str:
    size = path.stat().st_size
    with path.open("rb") as handle:
        if size > max_bytes:
            handle.seek(size - max_bytes)
        return handle.read(max_bytes).decode("utf-8", errors="replace")


def _secret_value_from_match(match: re.Match[str]) -> str:
    try:
        value = match.group("value")
    except IndexError:
        value = ""
    return value or match.group(0)


def _secret_match_is_placeholder(value: str) -> bool:
    normalized = value.strip().strip("\"'").lower()
    if not normalized:
        return True
    if normalized in SECRET_PLACEHOLDER_VALUES:
        return True
    if normalized.startswith(("$", "${", "{{", "<")):
        return True
    if "redacted" in normalized or "example" in normalized:
        return True
    if re.fullmatch(r"(?:sha256:)?[a-f0-9]{64}", normalized):
        return True
    return False


def _scan_secret_text(
    text: str,
    *,
    source: str,
    field: str,
) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    for pattern in SECRET_LEAK_PATTERNS:
        regex = pattern["regex"]
        assert isinstance(regex, re.Pattern)
        for match in regex.finditer(text):
            value = _secret_value_from_match(match)
            if _secret_match_is_placeholder(value):
                continue
            findings.append(
                {
                    "source": source,
                    "field": field,
                    "line": _line_number_for_offset(text, match.start()),
                    "rule_id": pattern["id"],
                    "severity": pattern["severity"],
                }
            )
    return findings


def _secret_event_scan_query(limit: int, lookback_hours: int) -> str:
    limit = max(1, min(limit, 2000))
    lookback_hours = max(1, min(lookback_hours, 720))
    return f"""
SELECT set_config('rls.role', 'platform_admin', false);
WITH agent_rows AS (
    SELECT created_at,
           'alpha_agent_events'::text AS source,
           id::text AS row_id,
           jsonb_build_object(
             'message', message,
             'payload', payload,
             'notification_result', notification_result,
             'notification_error', notification_error
           ) AS fields
    FROM public.alpha_agent_events
    WHERE created_at >= now() - interval '{lookback_hours} hours'
    ORDER BY created_at DESC
    LIMIT {limit}
),
buddy_rows AS (
    SELECT created_at,
           'alpha_buddy_events'::text AS source,
           id::text AS row_id,
           jsonb_build_object(
             'title', title,
             'body', body,
             'payload', COALESCE(payload, '{{}}'::jsonb)
           ) AS fields
    FROM public.alpha_buddy_events
    WHERE created_at >= now() - interval '{lookback_hours} hours'
    ORDER BY created_at DESC
    LIMIT {limit}
),
flat AS (
    SELECT source, row_id, created_at, item.key AS field, item.value AS value
    FROM agent_rows
    CROSS JOIN LATERAL jsonb_each_text(fields) AS item(key, value)
    UNION ALL
    SELECT source, row_id, created_at, item.key AS field, item.value AS value
    FROM buddy_rows
    CROSS JOIN LATERAL jsonb_each_text(fields) AS item(key, value)
)
SELECT source,
       row_id,
       field,
       encode(convert_to(value, 'UTF8'), 'base64') AS value_b64
FROM flat
WHERE COALESCE(value, '') <> ''
ORDER BY created_at DESC
LIMIT {limit * 8};
""".strip()


def _decode_psql_b64(value: str) -> str:
    return base64.b64decode(value.encode("ascii"), validate=True).decode(
        "utf-8",
        errors="replace",
    )


def _scan_recent_event_fields(
    *,
    psql: Callable[[str], CommandResult] = run_psql,
    limit: int = SECRET_LEAK_DB_LIMIT,
    lookback_hours: int = SECRET_LEAK_DB_LOOKBACK_HOURS,
) -> tuple[list[dict[str, object]], int, str | None]:
    result = psql(_secret_event_scan_query(limit, lookback_hours), timeout=45)
    if result.returncode != 0:
        return [], 0, (result.stderr or result.stdout).strip()[:500]

    findings: list[dict[str, object]] = []
    fields_scanned = 0
    for row in parse_psql_rows(result.stdout):
        if len(row) < 4:
            continue
        source, row_id, field, value_b64 = row[:4]
        try:
            text = _decode_psql_b64(value_b64)
        except Exception:
            continue
        fields_scanned += 1
        findings.extend(
            _scan_secret_text(
                text,
                source=f"{source}:{row_id}",
                field=field,
            )
        )
    return findings, fields_scanned, None


def check_secrets_leakage_scan(
    repo_root: Path = REPO_ROOT,
    psql: Callable[[str], CommandResult] = run_psql,
) -> CheckResult:
    """Scan local logs and recent event payloads for leaked secret material."""
    findings: list[dict[str, object]] = []
    unreadable: list[str] = []
    files_scanned = 0

    for path in _iter_secret_log_files(repo_root):
        display = _display_path(path)
        try:
            text = _read_tail_text(path, SECRET_LEAK_MAX_FILE_BYTES)
        except OSError as exc:
            unreadable.append(f"{display}: {exc.__class__.__name__}")
            continue
        files_scanned += 1
        findings.extend(_scan_secret_text(text, source=display, field="file"))

    db_findings, db_fields_scanned, db_error = _scan_recent_event_fields(psql=psql)
    findings.extend(db_findings)

    metadata = {
        "log_roots": [
            _display_path(path) for path in _secret_leak_log_roots(repo_root)
        ],
        "log_files_scanned": files_scanned,
        "db_fields_scanned": db_fields_scanned,
        "db_lookback_hours": SECRET_LEAK_DB_LOOKBACK_HOURS,
        "unreadable_files": unreadable[:20],
        "db_error": db_error,
        "findings": findings[:50],
        "finding_count": len(findings),
    }
    if findings:
        severity = (
            "critical"
            if any(item["severity"] == "critical" for item in findings)
            else "high"
        )
        detail = "; ".join(
            f"{item['source']}:{item['field']} {item['rule_id']}"
            for item in findings[:8]
        )
        return CheckResult(
            name="secrets_leakage_scan",
            status="fail",
            severity=severity,
            summary="Secret-shaped values were found in logs or event payloads.",
            detail=detail,
            metadata=metadata,
        )
    if unreadable or db_error:
        warnings = []
        if unreadable:
            warnings.append("unreadable log files")
        if db_error:
            warnings.append("recent DB event scan failed")
        return CheckResult(
            name="secrets_leakage_scan",
            status="warn",
            severity="medium",
            summary="Secrets leakage scan could not inspect every source.",
            detail="; ".join(warnings),
            metadata=metadata,
        )
    return CheckResult(
        name="secrets_leakage_scan",
        status="pass",
        severity="info",
        summary=(
            "No secret-shaped values found in local logs or recent event payloads."
        ),
        metadata=metadata,
    )


def _egress_allowed_hosts() -> set[str]:
    configured = {item.lower() for item in _csv_env("PORCHLIGHT_EGRESS_ALLOWED_HOSTS")}
    return {item.lower() for item in EGRESS_ALLOWED_HOSTS} | configured


def _egress_allowed_suffixes() -> tuple[str, ...]:
    configured = tuple(
        item.lower() for item in _csv_env("PORCHLIGHT_EGRESS_ALLOWED_SUFFIXES")
    )
    return EGRESS_ALLOWED_SUFFIXES + configured


def _egress_scan_roots(repo_root: Path = REPO_ROOT) -> list[Path]:
    raw_paths = _csv_env("PORCHLIGHT_EGRESS_SCAN_PATHS") or list(
        EGRESS_SCAN_DEFAULT_PATHS
    )
    roots: list[Path] = []
    for raw_path in raw_paths:
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = repo_root / path
        if path.exists():
            roots.append(path)
    return roots


def _egress_log_roots(repo_root: Path = REPO_ROOT) -> list[Path]:
    raw_paths = _csv_env("PORCHLIGHT_EGRESS_LOG_PATHS") or list(
        EGRESS_LOG_DEFAULT_PATHS
    )
    roots: list[Path] = []
    for raw_path in raw_paths:
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = repo_root / path
        if path.exists():
            roots.append(path)
    return roots


def _should_scan_egress_file(path: Path) -> bool:
    if any(part in EGRESS_SCAN_EXCLUDED_PARTS for part in path.parts):
        return False
    rel = _display_path(path)
    if rel in EGRESS_NON_EGRESS_FILES:
        return False
    if any(
        all(part in path.parts for part in skipped_parts)
        for skipped_parts in EGRESS_NON_EGRESS_PATH_PARTS
    ):
        return False
    if path.is_dir():
        return False
    return path.suffix.lower() in EGRESS_SCAN_SUFFIXES or path.name == "Dockerfile"


def _iter_egress_source_files(repo_root: Path = REPO_ROOT) -> list[Path]:
    files: list[Path] = []
    for root in _egress_scan_roots(repo_root):
        candidates = root.rglob("*") if root.is_dir() else [root]
        for candidate in candidates:
            if _should_scan_egress_file(candidate):
                files.append(candidate)
    return sorted(set(files))


def _iter_egress_log_files(repo_root: Path = REPO_ROOT) -> list[Path]:
    files: list[Path] = []
    for root in _egress_log_roots(repo_root):
        candidates = root.rglob("*") if root.is_dir() else [root]
        for candidate in candidates:
            name = candidate.name.lower()
            if _should_scan_secret_log(candidate) and any(
                term in name for term in EGRESS_LOG_NAME_TERMS
            ):
                files.append(candidate)
    return sorted(set(files))


URL_RE = re.compile(r"https?://[^\s\"'<>{}\\)}\]]+", re.IGNORECASE)


def _normalize_host(host: str) -> str:
    return host.strip().strip(".").lower()


def _host_is_private_or_local(host: str) -> bool:
    if host in {"localhost", "127.0.0.1", "::1"}:
        return True
    if re.fullmatch(r"10(?:\.\d{1,3}){3}", host):
        return True
    if re.fullmatch(r"192\.168(?:\.\d{1,3}){2}", host):
        return True
    if re.fullmatch(r"172\.(?:1[6-9]|2\d|3[0-1])(?:\.\d{1,3}){2}", host):
        return True
    if re.fullmatch(r"100(?:\.\d{1,3}){3}", host):
        return True
    return False


def _host_is_placeholder(host: str) -> bool:
    if not host:
        return True
    if "\\" in host or "{" in host or "}" in host or "$" in host:
        return True
    if host in {"host", "raw"}:
        return True
    if host.endswith(".fake.local"):
        return True
    if "." not in host and not _host_is_private_or_local(host):
        return True
    return False


def _extract_url_hosts(text: str) -> list[tuple[str, int]]:
    hosts: list[tuple[str, int]] = []
    for match in URL_RE.finditer(text):
        raw_url = match.group(0).rstrip(".,;:")
        parsed = urlparse(raw_url)
        host = _normalize_host(parsed.hostname or "")
        if host and not _host_is_placeholder(host):
            hosts.append((host, match.start()))
    return hosts


def _egress_host_allowed(host: str) -> bool:
    normalized = _normalize_host(host)
    if _host_is_private_or_local(normalized):
        return True
    if normalized in _egress_allowed_hosts():
        return True
    return any(normalized.endswith(suffix) for suffix in _egress_allowed_suffixes())


def _scan_egress_text(
    text: str,
    *,
    source: str,
) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    for host, offset in _extract_url_hosts(text):
        if _egress_host_allowed(host):
            continue
        findings.append(
            {
                "source": source,
                "line": _line_number_for_offset(text, offset),
                "host": host,
            }
        )
    return findings


def check_outbound_egress_drift(repo_root: Path = REPO_ROOT) -> CheckResult:
    """Detect newly introduced external destinations in code/config and logs."""
    findings: list[dict[str, object]] = []
    unreadable: list[str] = []
    source_files_scanned = 0
    log_files_scanned = 0
    observed_hosts: set[str] = set()

    for path in _iter_egress_source_files(repo_root):
        display = _display_path(path)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            unreadable.append(f"{display}: {exc.__class__.__name__}")
            continue
        source_files_scanned += 1
        observed_hosts.update(host for host, _offset in _extract_url_hosts(text))
        findings.extend(_scan_egress_text(text, source=display))

    for path in _iter_egress_log_files(repo_root):
        display = _display_path(path)
        try:
            text = _read_tail_text(path, SECRET_LEAK_MAX_FILE_BYTES)
        except OSError as exc:
            unreadable.append(f"{display}: {exc.__class__.__name__}")
            continue
        log_files_scanned += 1
        observed_hosts.update(host for host, _offset in _extract_url_hosts(text))
        findings.extend(_scan_egress_text(text, source=display))

    unique_unapproved = sorted({str(item["host"]) for item in findings})
    metadata = {
        "scan_roots": [_display_path(path) for path in _egress_scan_roots(repo_root)],
        "log_roots": [_display_path(path) for path in _egress_log_roots(repo_root)],
        "source_files_scanned": source_files_scanned,
        "log_files_scanned": log_files_scanned,
        "observed_hosts": sorted(observed_hosts),
        "unapproved_hosts": unique_unapproved,
        "findings": findings[:50],
        "finding_count": len(findings),
        "allowlist_count": len(_egress_allowed_hosts())
        + len(_egress_allowed_suffixes()),
        "unreadable_files": unreadable[:20],
    }
    if findings:
        detail = "; ".join(
            f"{item['source']}:{item['line']} {item['host']}" for item in findings[:8]
        )
        return CheckResult(
            name="outbound_egress_drift",
            status="fail",
            severity="high",
            summary="Unapproved outbound destination drift was detected.",
            detail=detail,
            metadata=metadata,
        )
    if unreadable:
        return CheckResult(
            name="outbound_egress_drift",
            status="warn",
            severity="medium",
            summary="Outbound egress drift scan could not inspect every source.",
            detail="; ".join(unreadable[:8]),
            metadata=metadata,
        )
    return CheckResult(
        name="outbound_egress_drift",
        status="pass",
        severity="info",
        summary="No unapproved outbound destinations found in scanned code or logs.",
        metadata=metadata,
    )


def _host_integrity_targets(repo_root: Path = REPO_ROOT) -> list[Path]:
    targets = [repo_root / item for item in HOST_INTEGRITY_REPO_FILES]
    if current_node_name() == "brain":
        targets.extend(Path(item).expanduser() for item in HOST_INTEGRITY_BRAIN_FILES)
    else:
        targets.extend(
            path
            for item in HOST_INTEGRITY_BRAIN_FILES
            if (path := Path(item).expanduser()).exists()
        )
    return targets


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_host_integrity(repo_root: Path = REPO_ROOT) -> CheckResult:
    checked: list[dict[str, object]] = []
    issues: list[str] = []
    warnings: list[str] = []

    for path in _host_integrity_targets(repo_root):
        display = _display_path(path)
        if not path.exists():
            issues.append(f"{display}: missing")
            continue
        if path.is_symlink():
            issues.append(f"{display}: symlink")
            continue
        try:
            stat_result = path.stat()
            mode = stat_result.st_mode & 0o777
            digest = _sha256_file(path)
        except OSError as exc:
            warnings.append(f"{display}: unreadable: {exc.__class__.__name__}")
            continue
        if mode & 0o022:
            issues.append(f"{display}: group/world writable mode {mode:o}")
        checked.append(
            {
                "path": display,
                "mode": f"{mode:o}",
                "sha256": digest,
                "size": stat_result.st_size,
            }
        )

    metadata = {
        "checked": checked,
        "issues": issues,
        "warnings": warnings,
    }
    if issues:
        return CheckResult(
            name="host_integrity",
            status="fail",
            severity="high",
            summary="Critical host files failed integrity safety checks.",
            detail="; ".join(issues[:8]),
            metadata=metadata,
        )
    if warnings:
        return CheckResult(
            name="host_integrity",
            status="warn",
            severity="medium",
            summary="Some critical host files could not be fully inspected.",
            detail="; ".join(warnings[:8]),
            metadata=metadata,
        )
    return CheckResult(
        name="host_integrity",
        status="pass",
        severity="info",
        summary=f"Host integrity checked {len(checked)} critical file(s).",
        metadata=metadata,
    )


def _parse_lsof_listener_line(line: str) -> dict[str, str] | None:
    parts = line.split()
    if len(parts) < 9 or parts[0] == "COMMAND":
        return None
    try:
        tcp_index = parts.index("TCP")
    except ValueError:
        return None
    if tcp_index + 1 >= len(parts):
        return None
    name = parts[tcp_index + 1]
    match = re.search(r"(.+):(\d+)$", name)
    if not match:
        return None
    host = match.group(1).strip("[]")
    return {
        "command": parts[0],
        "pid": parts[1],
        "user": parts[2],
        "host": host,
        "port": match.group(2),
        "name": name,
    }


def _listener_scope(host: str) -> str:
    normalized = host.lower()
    if normalized in {"127.0.0.1", "::1", "localhost"}:
        return "loopback"
    if normalized in {"*", "::"}:
        return "all_interfaces"
    if normalized.startswith("100."):
        return "tailscale"
    return "external"


def _listener_expected(listener: dict[str, str]) -> bool:
    command = listener["command"].lower()
    port = listener["port"]
    for expected_command, expected_port in EXPECTED_EXTERNAL_LISTENERS:
        if port == expected_port and command.startswith(expected_command):
            return True
    return False


def _parse_ps_line(line: str) -> dict[str, str] | None:
    stripped = line.strip()
    if not stripped:
        return None
    parts = stripped.split(None, 2)
    if len(parts) < 3 or not parts[0].isdigit():
        return None
    return {"pid": parts[0], "comm": parts[1], "args": parts[2]}


def check_runtime_exposure(
    command: Callable[..., CommandResult] = run_command,
) -> CheckResult:
    lsof = command(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN"], timeout=20)
    if lsof.returncode != 0:
        return CheckResult(
            name="runtime_exposure",
            status="warn",
            severity="medium",
            summary="Could not inspect listening TCP ports.",
            detail=(lsof.stderr or lsof.stdout).strip()[:500],
        )

    listeners = [
        parsed
        for line in lsof.stdout.splitlines()
        if (parsed := _parse_lsof_listener_line(line)) is not None
    ]
    unexpected_listeners: list[str] = []
    listener_metadata: list[dict[str, str]] = []
    for listener in listeners:
        scope = _listener_scope(listener["host"])
        listener["scope"] = scope
        listener_metadata.append(listener)
        if scope == "loopback":
            continue
        if not _listener_expected(listener):
            unexpected_listeners.append(
                f"{listener['command']} pid={listener['pid']} {listener['name']}"
            )

    ps = command(["ps", "-axo", "pid=,comm=,args="], timeout=20)
    suspicious_processes: list[str] = []
    process_samples: list[dict[str, str]] = []
    if ps.returncode == 0:
        for line in ps.stdout.splitlines():
            parsed = _parse_ps_line(line)
            if not parsed:
                continue
            args = parsed["args"]
            if any(pattern.search(args) for pattern in SUSPICIOUS_PROCESS_PATTERNS):
                suspicious_processes.append(f"{parsed['pid']} {args[:180]}")
                process_samples.append(parsed)
    else:
        suspicious_processes.append(
            f"ps failed: {(ps.stderr or ps.stdout).strip()[:200]}"
        )

    metadata = {
        "listeners": listener_metadata,
        "unexpected_listeners": unexpected_listeners,
        "suspicious_processes": suspicious_processes,
        "process_samples": process_samples[:20],
    }
    if unexpected_listeners or suspicious_processes:
        details = []
        if unexpected_listeners:
            details.append(
                "unexpected listeners: " + "; ".join(unexpected_listeners[:8])
            )
        if suspicious_processes:
            details.append(
                "suspicious processes: " + "; ".join(suspicious_processes[:8])
            )
        return CheckResult(
            name="runtime_exposure",
            status="fail",
            severity="high",
            summary="Unexpected runtime exposure needs review.",
            detail="; ".join(details),
            metadata=metadata,
        )
    return CheckResult(
        name="runtime_exposure",
        status="pass",
        severity="info",
        summary=f"Runtime exposure scan checked {len(listeners)} listening TCP socket(s).",
        metadata=metadata,
    )


def _int_config(
    name: str, default: int, *, minimum: int = 1, maximum: int = 3650
) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def _json_object_from_output(output: str) -> dict:
    start = output.find("{")
    if start < 0:
        raise json.JSONDecodeError("missing JSON object", output, 0)
    parsed = json.loads(output[start:])
    return parsed if isinstance(parsed, dict) else {}


def _tailscale_bin() -> str:
    return (
        os.getenv("PORCHLIGHT_TAILSCALE_BIN", TAILSCALE_DEFAULT_BIN).strip()
        or "tailscale"
    )


def _normalize_dns_name(value: object) -> str:
    return str(value or "").strip().rstrip(".").lower()


def _tailnet_dns_from_ssh_target(value: object) -> str | None:
    target = str(value or "").strip()
    if not target:
        return None
    host = target.rsplit("@", 1)[-1]
    host = host.split(":", 1)[0]
    normalized = _normalize_dns_name(host)
    return normalized if normalized.endswith(".ts.net") else None


def _expected_tailscale_dns_by_node(node_map: dict[str, object]) -> dict[str, str]:
    expected = dict(TAILSCALE_EXPECTED_DNS_BY_NODE)
    for node, info in node_map.items():
        if not isinstance(info, dict):
            continue
        dns = _tailnet_dns_from_ssh_target(info.get("ssh_target"))
        if dns:
            expected[str(node)] = dns
    return expected


def _parse_tailscale_time(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw or raw.startswith("0001-01-01"):
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _tailscale_nodes_from_status(payload: dict) -> list[dict[str, object]]:
    nodes: list[dict[str, object]] = []

    def add_node(raw: object, role: str) -> None:
        if not isinstance(raw, dict):
            return
        nodes.append(
            {
                "role": role,
                "hostname": str(raw.get("HostName") or ""),
                "dns": _normalize_dns_name(raw.get("DNSName")),
                "ips": list(raw.get("TailscaleIPs") or []),
                "online": bool(raw.get("Online")),
                "last_seen": str(raw.get("LastSeen") or ""),
                "os": str(raw.get("OS") or ""),
                "tags": list(raw.get("Tags") or []),
            }
        )

    add_node(payload.get("Self"), "self")
    for peer in (payload.get("Peer") or {}).values():
        add_node(peer, "peer")
    return nodes


def _tailscale_node_label(node: dict[str, object]) -> str:
    return str(node.get("dns") or node.get("hostname") or "unknown")


def _node_matches_allowed_stale(node: dict[str, object], allowed: set[str]) -> bool:
    names = {
        str(node.get("hostname") or "").lower(),
        str(node.get("dns") or "").lower(),
    }
    return bool(names & allowed)


def _tailscale_api_token() -> str | None:
    return (
        _secret_or_env("PORCHLIGHT_TAILSCALE_API_TOKEN")
        or _secret_or_env("TAILSCALE_API_KEY")
        or _secret_or_env("TAILSCALE_API_TOKEN")
    )


def _tailscale_tailnet_name(status_payload: dict | None = None) -> str | None:
    configured = _secret_or_env("PORCHLIGHT_TAILSCALE_TAILNET") or _secret_or_env(
        "TAILSCALE_TAILNET"
    )
    if configured:
        return configured
    tailnet = (status_payload or {}).get("CurrentTailnet")
    if isinstance(tailnet, dict):
        return str(tailnet.get("Name") or "").strip() or None
    return None


def _tailscale_api_get(
    path: str,
    *,
    command: Callable[..., CommandResult] = run_command,
) -> tuple[int, dict]:
    token = _tailscale_api_token()
    if not token:
        return 0, {"message": "missing_token"}
    result = command(
        [
            "curl",
            "-sS",
            "--max-time",
            "20",
            "-H",
            f"Authorization: Bearer {token}",
            f"{TAILSCALE_API_BASE.rstrip('/')}{path}",
        ],
        timeout=25,
    )
    if result.returncode != 0:
        return result.returncode, {
            "message": (result.stderr or result.stdout).strip()[:500]
        }
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return 1, {"message": "invalid_json"}
    return 0, payload if isinstance(payload, dict) else {"message": "invalid_json"}


def _canonical_json_hash(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _expected_acl_hash() -> str | None:
    value = _secret_or_env("PORCHLIGHT_TAILSCALE_ACL_SHA256")
    if value and re.fullmatch(r"[a-fA-F0-9]{64}", value.strip()):
        return value.strip().lower()
    return None


def _expected_authorized_key_hashes() -> dict[str, str]:
    raw = (
        _secret_or_env("PORCHLIGHT_AUTHORIZED_KEYS_SHA256")
        or _secret_or_env("PORCHLIGHT_AUTHORIZED_KEYS_EXPECTED_SHA256")
        or ""
    ).strip()
    if not raw:
        return {}
    parsed: dict[str, str] = {}
    if raw.startswith("{"):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if isinstance(payload, dict):
            for node, digest in payload.items():
                digest_text = str(digest).strip().lower()
                if re.fullmatch(r"[a-f0-9]{64}", digest_text):
                    parsed[str(node).strip().lower()] = digest_text
        return parsed
    for item in raw.split(","):
        if "=" not in item:
            continue
        node, digest = item.split("=", 1)
        digest = digest.strip().lower()
        if re.fullmatch(r"[a-f0-9]{64}", digest):
            parsed[node.strip().lower()] = digest
    return parsed


TAILSCALE_PREFS_COMMAND = (
    'tsbin="${PORCHLIGHT_TAILSCALE_BIN:-/opt/homebrew/bin/tailscale}"; '
    'if [ -x "$tsbin" ]; then "$tsbin" debug prefs; '
    "elif command -v tailscale >/dev/null 2>&1; then tailscale debug prefs; "
    'else echo \'{"error":"tailscale_missing"}\'; exit 127; fi'
)
AUTHORIZED_KEYS_COMMAND = r"""python3 - <<'PY'
import hashlib
import json
import os

path = os.path.expanduser("~/.ssh/authorized_keys")
payload = {"path": path, "exists": os.path.exists(path)}
if payload["exists"]:
    stat_result = os.stat(path)
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    payload.update(
        mode=format(stat_result.st_mode & 0o777, "o"),
        size=stat_result.st_size,
        sha256=digest.hexdigest(),
    )
print(json.dumps(payload, sort_keys=True))
PY"""


def _prefs_run_ssh_enabled(payload: dict) -> bool | None:
    value = payload.get("RunSSH")
    return value if isinstance(value, bool) else None


def _acl_payload_policy(payload: dict) -> dict:
    nested = payload.get("acl")
    return nested if isinstance(nested, dict) else payload


def _risky_tailscale_ssh_rules(policy: dict) -> list[str]:
    risky: list[str] = []
    rules = policy.get("ssh")
    if not isinstance(rules, list):
        return risky
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict):
            continue
        src = [str(item) for item in rule.get("src") or []]
        dst = [str(item) for item in rule.get("dst") or []]
        users = [str(item) for item in rule.get("users") or []]
        action = str(rule.get("action") or "")
        broad_src = any(item in {"*", "autogroup:member"} for item in src)
        broad_dst = any(item in {"*", "autogroup:member"} for item in dst)
        root_access = any(item == "root" for item in users)
        if broad_src or broad_dst or (root_access and action != "check"):
            risky.append(
                f"ssh[{index}] action={action or 'unknown'} src={src} dst={dst} users={users}"
            )
    return risky


def check_tailscale_ssh_posture(
    node_map: dict[str, object] | None = None,
    *,
    command: Callable[..., CommandResult] = run_command,
    ssh: Callable[[str, str], CommandResult] = run_ssh,
    now: datetime | None = None,
) -> CheckResult:
    now = now or datetime.now(UTC)
    node_map = node_map or {}
    issues: list[str] = []
    warnings: list[str] = []

    status_result = command([_tailscale_bin(), "status", "--json"], timeout=20)
    if status_result.returncode != 0:
        return CheckResult(
            name="tailscale_ssh_posture",
            status="warn",
            severity="medium",
            summary="Could not inspect Tailscale device posture.",
            detail=(status_result.stderr or status_result.stdout).strip()[:500],
        )

    try:
        status_payload = _json_object_from_output(status_result.stdout)
    except json.JSONDecodeError:
        return CheckResult(
            name="tailscale_ssh_posture",
            status="warn",
            severity="medium",
            summary="Tailscale status output was not valid JSON.",
            detail=status_result.stdout.strip()[:500],
        )

    nodes = _tailscale_nodes_from_status(status_payload)
    node_by_dns = {
        str(node.get("dns")): node for node in nodes if str(node.get("dns") or "")
    }
    expected_dns_by_node = _expected_tailscale_dns_by_node(node_map)
    expected_status: dict[str, dict[str, object]] = {}
    for node, dns in expected_dns_by_node.items():
        observed = node_by_dns.get(dns)
        expected_status[node] = {
            "expected_dns": dns,
            "present": observed is not None,
            "online": bool(observed and observed.get("online")),
        }
        if observed is None:
            issues.append(f"{node}: missing expected Tailscale device {dns}")
        elif not observed.get("online"):
            issues.append(f"{node}: expected Tailscale device {dns} is offline")

    stale_after_days = _int_config(
        "PORCHLIGHT_TAILSCALE_STALE_AFTER_DAYS",
        TAILSCALE_DEFAULT_STALE_AFTER_DAYS,
    )
    stale_cutoff = now - timedelta(days=stale_after_days)
    allowed_stale = _csv_config_set("PORCHLIGHT_TAILSCALE_ALLOWED_STALE_DEVICES")
    stale_devices: list[dict[str, object]] = []
    for node in nodes:
        if node.get("online") or _node_matches_allowed_stale(node, allowed_stale):
            continue
        last_seen = _parse_tailscale_time(node.get("last_seen"))
        if last_seen and last_seen < stale_cutoff:
            stale_devices.append(
                {
                    "hostname": node.get("hostname"),
                    "dns": node.get("dns"),
                    "last_seen": last_seen.isoformat(),
                    "os": node.get("os"),
                }
            )
    if stale_devices:
        labels = [
            f"{item.get('dns') or item.get('hostname')} last_seen={item.get('last_seen')}"
            for item in stale_devices[:8]
        ]
        issues.append("stale Tailscale devices: " + "; ".join(labels))

    remote_enabled = remote_ssh_probe_enabled()
    allowed_tailscale_ssh_nodes = _csv_config_set(
        "PORCHLIGHT_TAILSCALE_SSH_ALLOWED_NODES"
    )
    prefs_by_node: dict[str, dict[str, object]] = {}
    authorized_keys_by_node: dict[str, dict[str, object]] = {}
    expected_key_hashes = _expected_authorized_key_hashes()

    if not remote_enabled:
        warnings.append(
            "remote SSH probe is not enabled; node SSH posture was not checked"
        )
    else:
        for node, info in node_map.items():
            if not isinstance(info, dict) or not info.get("ssh_target"):
                warnings.append(f"{node}: missing ssh_target for posture probe")
                continue
            target = str(info["ssh_target"])

            prefs_result = ssh(target, TAILSCALE_PREFS_COMMAND)
            if prefs_result.returncode != 0:
                warnings.append(
                    f"{node}: tailscale prefs probe failed: "
                    f"{(prefs_result.stderr or prefs_result.stdout).strip()[:160]}"
                )
            else:
                try:
                    prefs = _json_object_from_output(prefs_result.stdout)
                except json.JSONDecodeError:
                    warnings.append(f"{node}: tailscale prefs probe returned non-JSON")
                else:
                    run_ssh_enabled = _prefs_run_ssh_enabled(prefs)
                    prefs_by_node[str(node)] = {"RunSSH": run_ssh_enabled}
                    if (
                        run_ssh_enabled
                        and str(node).lower() not in allowed_tailscale_ssh_nodes
                    ):
                        issues.append(
                            f"{node}: Tailscale SSH is enabled but not allowlisted"
                        )

            keys_result = ssh(target, AUTHORIZED_KEYS_COMMAND)
            if keys_result.returncode != 0:
                warnings.append(
                    f"{node}: authorized_keys probe failed: "
                    f"{(keys_result.stderr or keys_result.stdout).strip()[:160]}"
                )
                continue
            try:
                keys_payload = _json_object_from_output(keys_result.stdout)
            except json.JSONDecodeError:
                warnings.append(f"{node}: authorized_keys probe returned non-JSON")
                continue
            authorized_keys_by_node[str(node)] = keys_payload
            if not keys_payload.get("exists"):
                warnings.append(f"{node}: authorized_keys is missing")
                continue
            mode = str(keys_payload.get("mode") or "")
            try:
                numeric_mode = int(mode, 8)
            except ValueError:
                numeric_mode = 0
            if numeric_mode & 0o022:
                issues.append(
                    f"{node}: authorized_keys is group/world writable mode {mode}"
                )
            observed_hash = str(keys_payload.get("sha256") or "").lower()
            expected_hash = expected_key_hashes.get(str(node).lower())
            if expected_hash and observed_hash != expected_hash:
                issues.append(f"{node}: authorized_keys hash drift")
            elif not expected_hash:
                warnings.append(
                    f"{node}: authorized_keys hash baseline is not configured"
                )

    acl_metadata: dict[str, object] = {"checked": False}
    tailnet_name = _tailscale_tailnet_name(status_payload)
    if not _tailscale_api_token():
        warnings.append(
            "Tailscale API token is not configured; ACL drift was not checked"
        )
    elif not tailnet_name:
        warnings.append("Tailscale tailnet name is unknown; ACL drift was not checked")
    else:
        rc, acl_payload = _tailscale_api_get(
            f"/tailnet/{quote(tailnet_name, safe='')}/acl",
            command=command,
        )
        if rc != 0 or acl_payload.get("message"):
            warnings.append(
                "Tailscale ACL API probe failed: "
                f"{str(acl_payload.get('message') or 'request_failed')[:160]}"
            )
        else:
            policy = _acl_payload_policy(acl_payload)
            acl_hash = _canonical_json_hash(policy)
            expected_hash = _expected_acl_hash()
            risky_rules = _risky_tailscale_ssh_rules(policy)
            acl_metadata = {
                "checked": True,
                "sha256": acl_hash,
                "ssh_rule_count": len(policy.get("ssh") or [])
                if isinstance(policy.get("ssh"), list)
                else 0,
                "risky_ssh_rules": risky_rules,
            }
            if risky_rules:
                issues.append(
                    "broad Tailscale SSH ACL rule(s): " + "; ".join(risky_rules[:4])
                )
            if expected_hash and acl_hash != expected_hash:
                issues.append("Tailscale ACL hash drift")
            elif not expected_hash:
                warnings.append("Tailscale ACL hash baseline is not configured")

    metadata = {
        "backend_state": status_payload.get("BackendState"),
        "tailnet": tailnet_name,
        "device_count": len(nodes),
        "expected_nodes": expected_status,
        "stale_after_days": stale_after_days,
        "stale_devices": stale_devices,
        "tailscale_ssh": prefs_by_node,
        "authorized_keys": authorized_keys_by_node,
        "acl": acl_metadata,
        "warnings": warnings,
        "issues": issues,
    }

    if issues:
        return CheckResult(
            name="tailscale_ssh_posture",
            status="fail",
            severity="high",
            summary="Tailscale/SSH posture needs remediation.",
            detail="; ".join(issues[:8]),
            metadata=metadata,
        )
    if warnings:
        return CheckResult(
            name="tailscale_ssh_posture",
            status="warn",
            severity="medium",
            summary="Tailscale/SSH posture has monitoring gaps to close.",
            detail="; ".join(warnings[:8]),
            metadata=metadata,
        )
    return CheckResult(
        name="tailscale_ssh_posture",
        status="pass",
        severity="info",
        summary=(
            f"Tailscale/SSH posture checked {len(nodes)} device(s), "
            f"{len(authorized_keys_by_node)} authorized_keys file(s), and ACL drift."
        ),
        metadata=metadata,
    )


def _pip_audit_counts(payload: dict) -> dict[str, int]:
    counts = _severity_counts()
    for dependency in payload.get("dependencies") or []:
        if not isinstance(dependency, dict):
            continue
        for vuln in dependency.get("vulns") or []:
            if not isinstance(vuln, dict):
                continue
            aliases = [str(item).lower() for item in vuln.get("aliases") or []]
            severity = str(vuln.get("severity") or "").lower()
            if severity not in counts:
                if any(item.startswith("ghsa-") for item in aliases):
                    severity = "unknown"
                else:
                    severity = "unknown"
            counts[severity] += 1
    return counts


def _npm_audit_counts(payload: dict) -> dict[str, int]:
    counts = _severity_counts()
    vulnerabilities = payload.get("vulnerabilities")
    if isinstance(vulnerabilities, dict):
        for item in vulnerabilities.values():
            if not isinstance(item, dict):
                continue
            severity = str(item.get("severity") or "unknown").lower()
            counts[severity if severity in counts else "unknown"] += 1
        return counts

    metadata = (
        payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    )
    vuln_meta = metadata.get("vulnerabilities")
    if isinstance(vuln_meta, dict):
        for severity in counts:
            value = vuln_meta.get(severity)
            if isinstance(value, int):
                counts[severity] += value
    return counts


def _merge_counts(items: list[dict[str, int]]) -> dict[str, int]:
    merged = _severity_counts()
    for item in items:
        for severity in merged:
            merged[severity] += int(item.get(severity) or 0)
    return merged


def _npm_audit_env() -> dict[str, str]:
    env = {**os.environ, "npm_config_audit_level": "low"}
    npm_path = Path(NPM_BIN)
    if npm_path.is_absolute():
        path = env.get("PATH", "")
        env["PATH"] = f"{npm_path.parent}:{path}" if path else str(npm_path.parent)
    return env


def check_dependency_cve_scan(
    command: Callable[..., CommandResult] = run_command,
) -> CheckResult:
    """Summarize Python/npm dependency vulnerability scanners without blocking if absent."""
    scanner_results: list[dict[str, object]] = []
    counts: list[dict[str, int]] = []
    scanners_attempted = 0
    scanners_available = 0

    for requirements in PYTHON_REQUIREMENTS:
        if not requirements.exists():
            continue
        scanners_attempted += 1
        result = command(
            [
                sys.executable,
                "-m",
                "pip_audit",
                "-r",
                str(requirements),
                "-f",
                "json",
            ],
            timeout=120,
        )
        if not result.stdout.strip():
            scanner_results.append(
                {
                    "scanner": "pip-audit",
                    "target": _display_path(requirements),
                    "available": False,
                    "error": (result.stderr or "no output").strip()[:300],
                }
            )
            continue
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            scanner_results.append(
                {
                    "scanner": "pip-audit",
                    "target": _display_path(requirements),
                    "available": False,
                    "error": "invalid_json",
                }
            )
            continue
        scanners_available += 1
        item_counts = _pip_audit_counts(payload)
        counts.append(item_counts)
        scanner_results.append(
            {
                "scanner": "pip-audit",
                "target": _display_path(requirements),
                "available": True,
                "counts": item_counts,
            }
        )

    if (UI_DIR / "package-lock.json").exists() or (
        UI_DIR / "npm-shrinkwrap.json"
    ).exists():
        scanners_attempted += 1
        result = command(
            [NPM_BIN, "audit", "--json", "--omit=dev"],
            timeout=120,
            env=_npm_audit_env(),
        )
        if not result.stdout.strip():
            scanner_results.append(
                {
                    "scanner": "npm-audit",
                    "target": "ui",
                    "available": False,
                    "error": (result.stderr or "no output").strip()[:300],
                }
            )
        else:
            try:
                payload = json.loads(result.stdout)
            except json.JSONDecodeError:
                scanner_results.append(
                    {
                        "scanner": "npm-audit",
                        "target": "ui",
                        "available": False,
                        "error": "invalid_json",
                    }
                )
            else:
                scanners_available += 1
                item_counts = _npm_audit_counts(payload)
                counts.append(item_counts)
                scanner_results.append(
                    {
                        "scanner": "npm-audit",
                        "target": "ui",
                        "available": True,
                        "counts": item_counts,
                    }
                )

    total = _merge_counts(counts)
    metadata = {
        "scanners_attempted": scanners_attempted,
        "scanners_available": scanners_available,
        "counts": total,
        "scanners": scanner_results,
    }
    critical_high = total["critical"] + total["high"]
    medium = total["medium"]
    if critical_high:
        return CheckResult(
            name="dependency_cve_scan",
            status="fail",
            severity="high",
            summary="Dependency vulnerability scanners found high or critical CVEs.",
            detail=f"{total['critical']} critical, {total['high']} high, {medium} medium",
            metadata=metadata,
        )
    if medium:
        return CheckResult(
            name="dependency_cve_scan",
            status="warn",
            severity="medium",
            summary="Dependency vulnerability scanners found medium CVEs.",
            detail=f"{medium} medium, {total['low']} low, {total['unknown']} unknown",
            metadata=metadata,
        )
    if scanners_attempted and scanners_available == 0:
        return CheckResult(
            name="dependency_cve_scan",
            status="warn",
            severity="medium",
            summary="Dependency vulnerability scan could not run on this node.",
            detail="Install pip-audit and ensure npm is available for full Porchlight coverage.",
            metadata=metadata,
        )
    return CheckResult(
        name="dependency_cve_scan",
        status="pass",
        severity="info",
        summary="Dependency vulnerability scanners reported no medium-or-higher CVEs.",
        metadata=metadata,
    )


def _financial_security_posture_token() -> str | None:
    return _secret_or_env("JARVIS_FIN_SECURITY_POSTURE_TOKEN") or _secret_or_env(
        "FINANCIAL_SECURITY_POSTURE_TOKEN"
    )


def _financial_security_posture_url() -> str:
    return (
        _secret_or_env("PORCHLIGHT_FINANCIAL_SECURITY_POSTURE_URL")
        or _secret_or_env("FINANCIAL_SECURITY_POSTURE_URL")
        or FINANCIAL_SECURITY_POSTURE_URL
    )


def _parse_sweep_report_time(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def check_sweep_tls_report_intake(
    psql: Callable[[str], CommandResult] = run_psql,
    now: datetime | None = None,
) -> CheckResult:
    """Verify Brain is receiving signed node-local Sweep TLS reports."""
    now = now or datetime.now(UTC)
    query = """
SELECT set_config('rls.role', 'platform_admin', false);
WITH latest AS (
    SELECT DISTINCT ON (payload->>'node')
           payload->>'node' AS node,
           severity,
           to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS created_at,
           payload->>'status' AS status,
           COALESCE(payload->>'days_remaining', '') AS days_remaining,
           COALESCE(payload->>'threshold_days', '30') AS threshold_days,
           COALESCE(payload->>'health_ok', '') AS health_ok
    FROM public.alpha_agent_events
    WHERE agent_id = 'sweep'
      AND event_type = 'sweep.tls_report'
      AND payload ? 'node'
    ORDER BY payload->>'node', created_at DESC
)
SELECT node, severity, created_at, status, days_remaining, threshold_days, health_ok
FROM latest
ORDER BY node;
""".strip()
    result = psql(query)
    if result.returncode != 0:
        return CheckResult(
            name="sweep_tls_report_intake",
            status="fail",
            severity="high",
            summary="Could not inspect node-local Sweep TLS report intake.",
            detail=(result.stderr or result.stdout).strip()[:500],
        )

    rows = parse_psql_rows(result.stdout)
    by_node: dict[str, dict[str, str]] = {}
    for row in rows:
        if len(row) < 7:
            continue
        (
            node,
            severity,
            created_at,
            status,
            days_remaining,
            threshold_days,
            health_ok,
        ) = row[:7]
        by_node[node] = {
            "severity": severity,
            "created_at": created_at,
            "status": status,
            "days_remaining": days_remaining,
            "threshold_days": threshold_days,
            "health_ok": health_ok,
        }

    failures: list[str] = []
    warnings: list[str] = []
    for node in SWEEP_TLS_REPORT_EXPECTED_NODES:
        report = by_node.get(node)
        if report is None:
            warnings.append(f"{node} has not posted a Sweep TLS report")
            continue

        created_at = _parse_sweep_report_time(report["created_at"])
        if created_at is None:
            warnings.append(f"{node} Sweep TLS report has an invalid timestamp")
        elif now - created_at > SWEEP_TLS_REPORT_STALE_AFTER:
            warnings.append(f"{node} Sweep TLS report is stale")

        status = report["status"]
        health_ok = report["health_ok"].lower()
        severity = report["severity"]
        if (
            status == "error"
            or health_ok == "false"
            or severity
            in {
                "error",
                "critical",
            }
        ):
            failures.append(f"{node} Sweep TLS report is failing")
            continue

        try:
            days_remaining = int(report["days_remaining"])
            threshold_days = int(report["threshold_days"] or "30")
        except ValueError:
            continue
        if days_remaining <= threshold_days and status not in {
            "renewed",
            "renewal_pending",
        }:
            warnings.append(
                f"{node} cert is inside the renewal window without pending renewal"
            )

    metadata = {
        "expected_nodes": list(SWEEP_TLS_REPORT_EXPECTED_NODES),
        "reported_nodes": sorted(by_node),
        "reports": by_node,
    }
    if failures:
        return CheckResult(
            name="sweep_tls_report_intake",
            status="fail",
            severity="high",
            summary="One or more node-local Sweep TLS reports are failing.",
            detail="; ".join((failures + warnings)[:10]),
            metadata=metadata,
        )
    if warnings:
        return CheckResult(
            name="sweep_tls_report_intake",
            status="warn",
            severity="medium",
            summary="Node-local Sweep TLS report intake needs attention.",
            detail="; ".join(warnings[:10]),
            metadata=metadata,
        )
    return CheckResult(
        name="sweep_tls_report_intake",
        status="pass",
        severity="info",
        summary="Brain has fresh signed Sweep TLS reports from all nodes.",
        metadata=metadata,
    )


def check_financial_security_posture(
    url: str | None = None,
    command: Callable[..., CommandResult] = run_command,
) -> CheckResult:
    """Read Financial's self-owned posture summary without pulling secrets into Alpha."""
    url = _financial_security_posture_url() if url is None else url
    token = _financial_security_posture_token()
    metadata: dict[str, object] = {"configured": bool(url and token)}
    if not url or not token:
        return CheckResult(
            name="financial_security_posture",
            status="warn",
            severity="medium",
            summary="Financial posture monitor is not configured.",
            detail=(
                "Set PORCHLIGHT_FINANCIAL_SECURITY_POSTURE_URL and "
                "JARVIS_FIN_SECURITY_POSTURE_TOKEN on Brain."
            ),
            metadata=metadata,
        )

    result = command(
        [
            "curl",
            "-sS",
            "--max-time",
            "15",
            "-H",
            f"Authorization: Bearer {token}",
            "-w",
            "\n%{http_code}",
            url,
        ],
        timeout=20,
    )
    if result.returncode != 0:
        return CheckResult(
            name="financial_security_posture",
            status="fail",
            severity="high",
            summary="Financial posture endpoint is unreachable.",
            detail=(result.stderr or result.stdout).strip()[:500],
            metadata=metadata,
        )

    body, _, status_text = result.stdout.rstrip("\n").rpartition("\n")
    if not status_text.isdigit():
        return CheckResult(
            name="financial_security_posture",
            status="fail",
            severity="high",
            summary="Financial posture endpoint returned an invalid HTTP response.",
            detail="curl did not emit an HTTP status code",
            metadata=metadata,
        )
    metadata["http_status"] = int(status_text)
    if status_text != "200":
        return CheckResult(
            name="financial_security_posture",
            status="fail",
            severity="high",
            summary="Financial posture endpoint rejected the monitor request.",
            detail=f"HTTP {status_text}",
            metadata=metadata,
        )

    try:
        payload = json.loads(body or "{}")
    except json.JSONDecodeError:
        return CheckResult(
            name="financial_security_posture",
            status="fail",
            severity="high",
            summary="Financial posture endpoint returned non-JSON.",
            detail="invalid_json",
            metadata=metadata,
        )
    if not isinstance(payload, dict) or payload.get("service") != "jarvis-financial":
        return CheckResult(
            name="financial_security_posture",
            status="fail",
            severity="high",
            summary="Financial posture endpoint returned an unexpected payload.",
            detail="missing jarvis-financial service marker",
            metadata=metadata,
        )

    remote_status = str(payload.get("status") or "fail")
    if remote_status not in {"pass", "warn", "fail"}:
        remote_status = "fail"
    counts = payload.get("counts") if isinstance(payload.get("counts"), dict) else {}
    controls = (
        payload.get("controls") if isinstance(payload.get("controls"), list) else []
    )
    metadata.update(
        {
            "remote_status": remote_status,
            "counts": counts,
            "controls": [
                {
                    "id": str(control.get("id") or ""),
                    "status": str(control.get("status") or ""),
                    "severity": str(control.get("severity") or ""),
                }
                for control in controls
                if isinstance(control, dict)
            ],
        }
    )
    if remote_status == "pass":
        return CheckResult(
            name="financial_security_posture",
            status="pass",
            severity="info",
            summary="Financial self-owned posture checks are passing.",
            detail=_financial_counts_detail(counts),
            metadata=metadata,
        )
    if remote_status == "warn":
        return CheckResult(
            name="financial_security_posture",
            status="warn",
            severity="medium",
            summary="Financial self-owned posture checks need review.",
            detail=_financial_counts_detail(counts),
            metadata=metadata,
        )
    return CheckResult(
        name="financial_security_posture",
        status="fail",
        severity="high",
        summary="Financial self-owned posture checks are failing.",
        detail=_financial_counts_detail(counts),
        metadata=metadata,
    )


def _financial_counts_detail(counts: object) -> str:
    if not isinstance(counts, dict):
        return ""
    return (
        f"{counts.get('pass', 0)} pass, "
        f"{counts.get('warn', 0)} warn, "
        f"{counts.get('fail', 0)} fail"
    )


def _github_branch_protection_repos() -> list[str]:
    configured = os.getenv("PORCHLIGHT_GITHUB_BRANCH_PROTECTION_REPOS", "").strip()
    if configured:
        repos = [item.strip() for item in configured.split(",")]
        return sorted({repo for repo in repos if repo})
    return list(DEFAULT_GITHUB_BRANCH_PROTECTION_REPOS)


def _github_required_checks() -> set[str]:
    configured = os.getenv("PORCHLIGHT_GITHUB_REQUIRED_CHECKS", "").strip()
    if not configured:
        return set(DEFAULT_GITHUB_REQUIRED_CHECKS)
    return {item.strip() for item in configured.split(",") if item.strip()}


def _github_api_get(
    path: str,
    *,
    command: Callable[..., CommandResult] = run_command,
) -> tuple[int, dict]:
    token = _secret_or_env("GITHUB_TOKEN")
    if not token:
        return 0, {"message": "missing_token"}
    result = command(
        [
            "curl",
            "-sS",
            "--max-time",
            "20",
            "-H",
            "Accept: application/vnd.github+json",
            "-H",
            f"Authorization: Bearer {token}",
            f"https://api.github.com{path}",
        ],
        timeout=25,
    )
    if result.returncode != 0:
        return result.returncode, {
            "message": (result.stderr or result.stdout).strip()[:500]
        }
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return 1, {"message": "invalid_json"}
    return 0, payload if isinstance(payload, dict) else {"message": "invalid_json"}


def _status_check_contexts(protection: dict) -> set[str]:
    checks = protection.get("required_status_checks")
    if not isinstance(checks, dict):
        return set()
    contexts = set()
    raw_contexts = checks.get("contexts")
    if isinstance(raw_contexts, list):
        contexts.update(str(item) for item in raw_contexts if item)
    raw_checks = checks.get("checks")
    if isinstance(raw_checks, list):
        for item in raw_checks:
            if isinstance(item, dict) and item.get("context"):
                contexts.add(str(item["context"]))
    return contexts


def check_github_branch_protection_drift(
    command: Callable[..., CommandResult] = run_command,
) -> CheckResult:
    repos = _github_branch_protection_repos()
    branch = os.getenv("PORCHLIGHT_GITHUB_BRANCH", "main").strip() or "main"
    required_checks = _github_required_checks()
    if not _secret_or_env("GITHUB_TOKEN"):
        return CheckResult(
            name="github_branch_protection_drift",
            status="warn",
            severity="medium",
            summary="GitHub API token is not configured for branch-protection monitoring.",
            detail="Set GITHUB_TOKEN on Brain secrets.",
            metadata={"repos": repos, "branch": branch},
        )

    findings: list[str] = []
    warnings: list[str] = []
    repo_results: list[dict[str, object]] = []
    for repo in repos:
        rc, payload = _github_api_get(
            f"/repos/{repo}/branches/{branch}/protection",
            command=command,
        )
        if rc != 0 or payload.get("message") in {
            "Not Found",
            "missing_token",
            "invalid_json",
        }:
            findings.append(f"{repo}:{branch} protection unavailable")
            repo_results.append(
                {
                    "repo": repo,
                    "branch": branch,
                    "status": "unavailable",
                    "message": payload.get("message"),
                }
            )
            continue
        contexts = _status_check_contexts(payload)
        missing_checks = sorted(required_checks - contexts)
        reviews = payload.get("required_pull_request_reviews")
        status_checks = payload.get("required_status_checks")
        has_reviews = isinstance(reviews, dict)
        has_status_checks = isinstance(status_checks, dict)
        required_review_count = (
            int(reviews.get("required_approving_review_count") or 0)
            if isinstance(reviews, dict)
            else 0
        )
        dismisses_stale_reviews = (
            bool(reviews.get("dismiss_stale_reviews"))
            if isinstance(reviews, dict)
            else False
        )
        requires_last_push_approval = (
            bool(reviews.get("require_last_push_approval"))
            if isinstance(reviews, dict)
            else False
        )
        strict_status_checks = (
            bool(status_checks.get("strict"))
            if isinstance(status_checks, dict)
            else False
        )
        if not has_reviews:
            findings.append(f"{repo}:{branch} missing PR-review requirement")
        elif required_review_count < 1:
            findings.append(f"{repo}:{branch} requires no approving review")
        if has_reviews and not dismisses_stale_reviews:
            findings.append(f"{repo}:{branch} does not dismiss stale reviews")
        if has_reviews and not requires_last_push_approval:
            findings.append(f"{repo}:{branch} does not require last-push approval")
        if required_checks and missing_checks:
            findings.append(
                f"{repo}:{branch} missing required checks: {', '.join(missing_checks)}"
            )
        elif not has_status_checks:
            warnings.append(f"{repo}:{branch} has no required status checks")
        if has_status_checks and not strict_status_checks:
            findings.append(f"{repo}:{branch} does not require up-to-date branches")
        repo_results.append(
            {
                "repo": repo,
                "branch": branch,
                "status": "checked",
                "has_pr_reviews": has_reviews,
                "has_status_checks": has_status_checks,
                "required_approving_review_count": required_review_count,
                "dismiss_stale_reviews": dismisses_stale_reviews,
                "require_last_push_approval": requires_last_push_approval,
                "strict_status_checks": strict_status_checks,
                "required_checks": sorted(required_checks),
                "contexts": sorted(contexts),
            }
        )

    metadata = {
        "repos": repo_results,
        "branch": branch,
        "required_checks": sorted(required_checks),
    }
    if findings:
        return CheckResult(
            name="github_branch_protection_drift",
            status="fail",
            severity="high",
            summary="GitHub branch protection drift needs remediation.",
            detail="; ".join(findings[:8]),
            metadata=metadata,
        )
    if warnings:
        return CheckResult(
            name="github_branch_protection_drift",
            status="warn",
            severity="medium",
            summary="GitHub branch protection is enabled but has weaker-than-target controls.",
            detail="; ".join(warnings[:8]),
            metadata=metadata,
        )
    return CheckResult(
        name="github_branch_protection_drift",
        status="pass",
        severity="info",
        summary=f"GitHub branch protection is present for {len(repos)} repo(s).",
        metadata=metadata,
    )


def check_route_db_access(
    routes_dir: Path = ROUTES_DIR,
    reviewed: dict[str, str] = REVIEWED_ROUTE_DB_ACCESS,
) -> CheckResult:
    raw_access: dict[str, int] = {}
    uses_rls_helper: list[str] = []
    for path in sorted(routes_dir.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        count = (
            text.count("pool.acquire(")
            + text.count("asyncpg.connect(")
            + text.count("create_pool(")
        )
        if count:
            raw_access[path.name] = count
        if "rls_connection(" in text or "platform_admin_connection(" in text:
            uses_rls_helper.append(path.name)

    unreviewed = sorted(set(raw_access) - set(reviewed))
    stale_reviews = sorted(set(reviewed) - set(raw_access))
    metadata = {
        "raw_route_files": raw_access,
        "reviewed": reviewed,
        "uses_rls_helper": uses_rls_helper,
        "unreviewed": unreviewed,
        "stale_reviews": stale_reviews,
    }

    if unreviewed:
        return CheckResult(
            name="route_db_access_review",
            status="fail",
            severity="high",
            summary="One or more route modules use direct DB access without a reviewed RLS rationale.",
            detail=", ".join(unreviewed),
            metadata=metadata,
        )

    if stale_reviews:
        return CheckResult(
            name="route_db_access_review",
            status="warn",
            severity="low",
            summary="Route DB access allowlist has stale entries to clean up.",
            detail=", ".join(stale_reviews),
            metadata=metadata,
        )

    return CheckResult(
        name="route_db_access_review",
        status="pass",
        severity="info",
        summary=f"{len(raw_access)} route modules with direct DB access have reviewed RLS rationales.",
        metadata=metadata,
    )


def build_report(checks: list[CheckResult]) -> dict[str, object]:
    failing = [check for check in checks if check.status == "fail"]
    warning = [check for check in checks if check.status == "warn"]
    severity = highest_severity(checks)
    status = "pass"
    if failing:
        status = "fail"
    elif warning:
        status = "warn"
    return {
        "agent": "Porchlight",
        "generated_at": datetime.now(UTC).isoformat(),
        "status": status,
        "severity": severity,
        "counts": {
            "checks": len(checks),
            "failing": len(failing),
            "warning": len(warning),
            "passing": sum(1 for check in checks if check.status == "pass"),
        },
        "checks": [asdict(check) for check in checks],
    }


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def buddy_event_body(report: dict[str, object]) -> str:
    counts = report["counts"]
    lines = [
        f"Status: {report['status']} / severity: {report['severity']}",
        (
            f"Checks: {counts['passing']} pass, "
            f"{counts['warning']} warning, {counts['failing']} failing"
        ),
    ]
    issues = [
        check for check in report["checks"] if check["status"] in {"fail", "warn"}
    ]
    for check in issues[:6]:
        detail = f" — {check['detail']}" if check.get("detail") else ""
        lines.append(f"- {check['name']}: {check['summary']}{detail}")
    return "\n".join(lines)[:3500]


def post_buddy_event(
    report: dict[str, object],
    psql: Callable[[str], CommandResult] = run_psql,
) -> CommandResult:
    status = str(report["status"])
    event_type = "alert" if status in {"fail", "warn"} else "system"
    priority = 3 if report["severity"] in {"high", "critical"} else 2
    title = (
        "Porchlight security alert"
        if event_type == "alert"
        else "Porchlight security sweep"
    )
    body = buddy_event_body(report)
    payload = json.dumps(report, separators=(",", ":"), default=str)
    query = f"""
SELECT public.record_buddy_event(
  NULL,
  {_sql_literal(event_type)},
  {_sql_literal(title)},
  {_sql_literal(body)},
  {priority},
  'porchlight',
  {_sql_literal(payload)}::jsonb
);
""".strip()
    return psql(query)


def agent_event_severity(report: dict[str, object]) -> str:
    if report["status"] == "pass":
        return "info"
    if report["status"] == "warn" and not has_notifiable_security_condition(report):
        return "info"
    if report["status"] == "warn":
        return "warning"
    if report["severity"] == "critical":
        return "critical"
    return "error"


def agent_event_type(report: dict[str, object]) -> str:
    if report["status"] == "pass":
        return "security.sweep_ok"
    if report["status"] == "warn":
        return "security.sweep_warning"
    return "security.sweep_failed"


def agent_event_title(report: dict[str, object]) -> str:
    if report["status"] == "pass":
        return "Porchlight security sweep"
    return "Porchlight security alert"


ROUTINE_WARNING_CHECKS = {
    "secret_rotation",
}


def is_routine_warning_check(check: dict[str, object]) -> bool:
    name = str(check.get("name") or "")
    if name in ROUTINE_WARNING_CHECKS:
        return True
    metadata = check.get("metadata")
    if not isinstance(metadata, dict):
        return False
    return (
        name == "postgres_role_safety"
        and metadata.get("accepted_exception") == "postgres_bootstrap_role_superuser"
        and metadata.get("bootstrap_risk") == "accepted_contained"
    )


def has_notifiable_security_condition(report: dict[str, object]) -> bool:
    for raw_check in report.get("checks", []):
        if not isinstance(raw_check, dict):
            continue
        status = raw_check.get("status")
        severity = str(raw_check.get("severity") or "info")
        if status == "fail":
            return True
        if status != "warn":
            continue
        if SEVERITY_RANK.get(severity, 0) >= SEVERITY_RANK["high"]:
            return True
        if not is_routine_warning_check(raw_check):
            return True
    return False


def record_agent_event(
    report: dict[str, object],
    *,
    notification_status: str,
    psql: Callable[[str], CommandResult] = run_psql,
) -> CommandResult:
    payload = json.dumps(report, separators=(",", ":"), default=str)
    query = f"""
SELECT public.record_agent_event(
  'porchlight',
  {_sql_literal(agent_event_type(report))},
  {_sql_literal(agent_event_title(report))},
  {_sql_literal(buddy_event_body(report))},
  {_sql_literal(agent_event_severity(report))},
  {_sql_literal(payload)}::jsonb,
  NULL,
  {_sql_literal("porchlight:" + str(report["generated_at"]))},
  '{PORCHLIGHT_CHANNEL_KEY}',
  {_sql_literal(notification_status)}
);
""".strip()
    return psql(query)


def mark_agent_event_notification(
    event_id: str,
    status: str,
    *,
    result: dict[str, object] | None = None,
    error: str | None = None,
    psql: Callable[[str], CommandResult] = run_psql,
) -> CommandResult:
    payload = json.dumps(result or {}, separators=(",", ":"), default=str)
    error_sql = "NULL" if error is None else _sql_literal(error[:500])
    query = f"""
SELECT public.mark_agent_event_notification(
  {_sql_literal(event_id)}::uuid,
  {_sql_literal(status)},
  {_sql_literal(payload)}::jsonb,
  {error_sql}
);
""".strip()
    return psql(query)


def notify_mattermost(
    report: dict[str, object],
    *,
    command: Callable[..., CommandResult] = run_command,
) -> tuple[str, dict[str, object]]:
    gateway_token = _secret_or_env("GATEWAY_TOKEN")
    if not gateway_token:
        raise RuntimeError("GATEWAY_TOKEN is not configured for Mattermost alert proxy")
    payload = {
        "title": agent_event_title(report),
        "message": buddy_event_body(report),
        "severity": agent_event_severity(report),
        "source": "alpha",
        "channel_key": PORCHLIGHT_CHANNEL_KEY,
    }
    result = command(
        [
            "curl",
            "-sS",
            "-m",
            "15",
            "-X",
            "POST",
            "-H",
            "Content-Type: application/json",
            "-H",
            f"Authorization: Bearer {gateway_token}",
            "-H",
            f"X-JARVIS-Idempotency-Key: porchlight:{report['generated_at']}",
            "-d",
            json.dumps(payload),
            f"{GATEWAY_URL.rstrip('/')}/v1/notify/mattermost",
        ],
        timeout=20,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip()[:500])
    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("gateway_non_json_response") from exc
    if parsed.get("status") != "sent":
        raise RuntimeError(str(parsed.get("detail") or "gateway_rejected"))
    return str(parsed.get("channel_key") or PORCHLIGHT_CHANNEL_KEY), parsed


def post_agent_event_alert(
    report: dict[str, object],
    *,
    psql: Callable[[str], CommandResult] = run_psql,
    command: Callable[..., CommandResult] = run_command,
) -> CommandResult:
    event_result = record_agent_event(report, notification_status="pending", psql=psql)
    if event_result.returncode != 0:
        return event_result
    event_id = event_result.stdout.strip().splitlines()[-1].strip()
    if not event_id:
        return CommandResult(1, "", "record_agent_event returned no event id")

    try:
        _channel_key, notify_result = notify_mattermost(report, command=command)
    except Exception as exc:
        mark_agent_event_notification(
            event_id,
            "failed",
            result={"provider": "mattermost"},
            error=str(exc),
            psql=psql,
        )
        return CommandResult(1, "", str(exc))

    mark_result = mark_agent_event_notification(
        event_id,
        "sent",
        result=notify_result,
        psql=psql,
    )
    if mark_result.returncode != 0:
        return mark_result
    return CommandResult(0, event_id, "")


def write_report(report: dict[str, object], path: Path = REPORT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def run_sweep(args: argparse.Namespace) -> dict[str, object]:
    node_map = load_json(NODE_MAP_PATH)
    checks = [
        check_database_rls(),
        check_postgres_role_safety(),
        check_postgres_hba_safety(),
        check_secret_rotation(),
        check_secret_live_verification(node_map=node_map),
        check_security_launchagents(node_map=node_map),
        check_token_rotation_logs(
            node_map=node_map,
            max_age_hours=args.max_token_log_age_hours,
        ),
        check_backup_recovery(node_map=node_map),
        check_cloudflare_access(args.cloudflare_access_url),
        check_cloudflare_access_policy_drift(),
        check_cloudflare_audit_logs(window_hours=args.cloudflare_audit_window_hours),
        check_dependency_cve_scan(),
        check_malware_scan_repo_freshness(),
        check_code_malware_scan(),
        check_secrets_leakage_scan(),
        check_outbound_egress_drift(),
        check_host_integrity(),
        check_runtime_exposure(),
        check_tailscale_ssh_posture(node_map=node_map),
        check_sweep_tls_report_intake(),
        check_financial_security_posture(),
        check_github_branch_protection_drift(),
        check_route_db_access(),
    ]
    return build_report(checks)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Porchlight security sweep for JARVIS Alpha",
    )
    parser.add_argument("--json", action="store_true", help="Print full JSON report")
    parser.add_argument(
        "--always-report",
        action="store_true",
        help="Post a notification event even when every check passes",
    )
    parser.add_argument(
        "--report-warnings",
        action="store_true",
        help="Post a notification event for warnings as well as failures",
    )
    parser.add_argument(
        "--no-buddy-event",
        action="store_true",
        help="Do not post Buddy, Alpha agent, or Mattermost notifications",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 2 when Porchlight finds warning/failing checks",
    )
    parser.add_argument(
        "--max-token-log-age-hours",
        type=int,
        default=36,
        help="Freshness window for token rotation success logs",
    )
    parser.add_argument(
        "--cloudflare-access-url",
        default=CLOUDFLARE_ACCESS_URL,
        help="Public URL expected to be gated by Cloudflare Access",
    )
    parser.add_argument(
        "--cloudflare-audit-window-hours",
        type=int,
        default=24,
        help="Cloudflare audit-log lookback window in hours",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_sweep(args)
    write_report(report)

    should_post = args.always_report or (
        (report["status"] == "fail" or args.report_warnings)
        and has_notifiable_security_condition(report)
    )
    if not args.no_buddy_event and should_post:
        agent_result = post_agent_event_alert(report)
        if agent_result.returncode != 0:
            print(
                "Porchlight: Alpha agent/Mattermost alert failed: "
                + (agent_result.stderr or agent_result.stdout).strip(),
                file=sys.stderr,
            )

        event_result = post_buddy_event(report)
        if event_result.returncode != 0:
            print(
                "Porchlight: Buddy event post failed: "
                + (event_result.stderr or event_result.stdout).strip(),
                file=sys.stderr,
            )
    elif not args.no_buddy_event and report["status"] in {"pass", "warn"}:
        status_result = record_agent_event(
            report,
            notification_status="not_requested",
        )
        if status_result.returncode != 0:
            print(
                "Porchlight: Alpha agent status event failed: "
                + (status_result.stderr or status_result.stdout).strip(),
                file=sys.stderr,
            )

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        counts = report["counts"]
        print(
            "Porchlight "
            f"{report['status']} ({report['severity']}): "
            f"{counts['passing']} pass, {counts['warning']} warn, "
            f"{counts['failing']} fail"
        )
        print(f"Report: {REPORT_PATH}")

    if args.strict and report["status"] != "pass":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
