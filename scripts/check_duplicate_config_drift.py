#!/usr/bin/env python3
"""Fail CI when duplicate config filenames drift apart.

TD-106: stale duplicate configs have caused real operational confusion
(`alpha.nginx.conf`, LaunchAgent plists). This guard is intentionally simple:
if two active config files share the same basename, their bytes must match.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


CONFIG_SUFFIXES = (".conf", ".plist", ".yaml", ".yml")
SKIP_DIR_NAMES = {
    ".git",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "logs",
    "node_modules",
}
SKIP_PATH_PREFIXES = (Path("ui/dist"),)


@dataclass(frozen=True)
class DuplicateConfigDrift:
    basename: str
    paths: tuple[Path, ...]
    digests: tuple[str, ...]


def _is_skipped(path: Path) -> bool:
    return any(part in SKIP_DIR_NAMES for part in path.parts) or any(
        path == prefix or path.is_relative_to(prefix) for prefix in SKIP_PATH_PREFIXES
    )


def _is_config_file(path: Path) -> bool:
    return path.suffix in CONFIG_SUFFIXES


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def candidate_config_files(
    root: Path,
    scan_roots: Sequence[str] | None = None,
) -> list[Path]:
    root = root.resolve()
    bases: Iterable[Path]
    if scan_roots:
        bases = (root / scan_root for scan_root in scan_roots)
    else:
        bases = (root,)

    files: list[Path] = []
    for base in bases:
        if not base.exists():
            continue
        if base.is_file():
            rel = base.relative_to(root)
            if _is_config_file(rel) and not _is_skipped(rel):
                files.append(base)
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(root)
            if _is_skipped(rel) or not _is_config_file(rel):
                continue
            files.append(path)
    return sorted(files)


def find_duplicate_config_drift(
    root: Path,
    scan_roots: Sequence[str] | None = None,
) -> list[DuplicateConfigDrift]:
    root = root.resolve()
    grouped: dict[str, list[Path]] = defaultdict(list)
    for path in candidate_config_files(root, scan_roots=scan_roots):
        grouped[path.name].append(path)

    drifts: list[DuplicateConfigDrift] = []
    for basename, paths in grouped.items():
        if len(paths) < 2:
            continue
        digests = {_sha256(path) for path in paths}
        if len(digests) > 1:
            drifts.append(
                DuplicateConfigDrift(
                    basename=basename,
                    paths=tuple(path.relative_to(root) for path in paths),
                    digests=tuple(sorted(digests)),
                )
            )
    return sorted(drifts, key=lambda drift: drift.basename)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Detect divergent duplicate config filenames."
    )
    parser.add_argument(
        "root",
        nargs="?",
        default=".",
        help="Repository root to scan. Defaults to current directory.",
    )
    parser.add_argument(
        "--scan-root",
        action="append",
        dest="scan_roots",
        help="Relative path to scan. May be repeated.",
    )
    args = parser.parse_args(argv)

    root = Path(args.root)
    drifts = find_duplicate_config_drift(root, scan_roots=args.scan_roots)
    if not drifts:
        print("duplicate config drift guard passed: no divergent duplicates found.")
        return 0

    print("duplicate config drift guard failed.", file=sys.stderr)
    print(
        "Files with the same config basename must be byte-identical or renamed.",
        file=sys.stderr,
    )
    for drift in drifts:
        print(f"\n{drift.basename}", file=sys.stderr)
        for path in drift.paths:
            print(f"  - {path}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
