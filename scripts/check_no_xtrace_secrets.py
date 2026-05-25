#!/usr/bin/env python3
"""Fail CI when active repo files enable shell xtrace.

TD-129: shell xtrace can print commands that source secret files. That makes
`set -x`, `bash -x`, and related forms unsafe in start/deploy/smoke scripts and
agent prompt config.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


DEFAULT_SCAN_ROOTS = (
    "scripts",
    "launchagents",
    ".github/workflows",
    ".claude",
    ".forge",
    ".jarvis-hooks",
)
SKIP_DIR_NAMES = {
    ".git",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "node_modules",
}
SELF_PATH = Path("scripts/check_no_xtrace_secrets.py")


@dataclass(frozen=True)
class XtracePattern:
    name: str
    regex: re.Pattern[str]


@dataclass(frozen=True)
class XtraceFinding:
    path: Path
    line_number: int
    rule: str


XTRACE_PATTERNS = (
    XtracePattern(
        "shell xtrace option",
        re.compile(r"\bset\s+-[A-Za-z]*x[A-Za-z]*(?:\s|$)"),
    ),
    XtracePattern(
        "shell xtrace long option",
        re.compile(r"\bset\s+-o\s+xtrace\b"),
    ),
    XtracePattern(
        "shell command with xtrace",
        re.compile(r"\b(?:bash|zsh|sh)\s+-[A-Za-z]*x[A-Za-z]*(?:\s|$)"),
    ),
    XtracePattern(
        "shell command with xtrace long option",
        re.compile(r"\b(?:bash|zsh|sh)\s+-o\s+xtrace\b"),
    ),
    XtracePattern(
        "xtrace output redirection",
        re.compile(r"\bBASH_XTRACEFD\b"),
    ),
)


def _is_skipped(path: Path) -> bool:
    return any(part in SKIP_DIR_NAMES for part in path.parts)


def _candidate_files(root: Path, scan_roots: Sequence[str]) -> list[Path]:
    files: list[Path] = []
    for scan_root in scan_roots:
        base = root / scan_root
        if not base.exists():
            continue
        if base.is_file():
            rel_path = base.relative_to(root)
            if rel_path != SELF_PATH and not _is_skipped(rel_path):
                files.append(base)
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            rel_path = path.relative_to(root)
            if rel_path == SELF_PATH or _is_skipped(rel_path):
                continue
            files.append(path)
    return sorted(files)


def find_xtrace_findings(
    root: Path,
    scan_roots: Sequence[str] = DEFAULT_SCAN_ROOTS,
) -> list[XtraceFinding]:
    findings: list[XtraceFinding] = []
    root = root.resolve()

    for path in _candidate_files(root, scan_roots):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue

        rel_path = path.relative_to(root)
        for line_number, line in enumerate(lines, start=1):
            for pattern in XTRACE_PATTERNS:
                if pattern.regex.search(line):
                    findings.append(
                        XtraceFinding(
                            path=rel_path,
                            line_number=line_number,
                            rule=pattern.name,
                        )
                    )
    return findings


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ban shell xtrace in active jarvis-alpha files."
    )
    parser.add_argument(
        "root",
        nargs="?",
        default=".",
        help="Repository root to scan. Defaults to the current directory.",
    )
    parser.add_argument(
        "--scan-root",
        action="append",
        dest="scan_roots",
        help="Relative path to scan. May be repeated.",
    )
    args = parser.parse_args(argv)

    scan_roots = tuple(args.scan_roots) if args.scan_roots else DEFAULT_SCAN_ROOTS
    findings = find_xtrace_findings(Path(args.root), scan_roots=scan_roots)
    if not findings:
        print("xtrace secret guard passed: no xtrace patterns in active files.")
        return 0

    print(
        "xtrace secret guard failed: unsafe shell tracing is present.", file=sys.stderr
    )
    print(
        "Use explicit echo statements or non-tracing syntax checks instead.",
        file=sys.stderr,
    )
    for finding in findings:
        print(
            f"{finding.path}:{finding.line_number}: {finding.rule}",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
