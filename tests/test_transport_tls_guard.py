"""Guard runtime code against disabling TLS verification."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCAN_ROOTS = ("brain", "gateway", "common")
ALLOWLIST: set[tuple[str, str]] = set()

PATTERNS = {
    "httpx verify=False": re.compile(r"verify\s*=\s*False"),
    "curl -k": re.compile(r"curl\s+[^\\n]*(?:-[A-Za-z]*k[A-Za-z]*|--insecure)"),
    '"-k" curl arg': re.compile(r'"-[A-Za-z]*k[A-Za-z]*"'),
    "--insecure": re.compile(r"--insecure"),
}


def _runtime_python_files() -> list[Path]:
    files: list[Path] = []
    for root in SCAN_ROOTS:
        base = REPO_ROOT / root
        if base.exists():
            files.extend(base.rglob("*.py"))
    return files


def test_runtime_code_does_not_disable_tls_verification():
    findings: list[str] = []
    for path in _runtime_python_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for label, pattern in PATTERNS.items():
                if not pattern.search(line):
                    continue
                if any((rel, token) in ALLOWLIST for token in ("curl -sk", '"-sk"')):
                    continue
                findings.append(f"{rel}:{lineno}: {label}: {line.strip()}")

    assert not findings, (
        "Runtime code must not disable TLS verification. Use verified HTTPS; "
        "if a local/self-signed device truly needs an exception, document and "
        "allowlist that exact call site.\n" + "\n".join(findings)
    )
