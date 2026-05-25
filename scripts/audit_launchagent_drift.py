#!/usr/bin/env python3
"""
Audit LaunchAgent expected-vs-loaded drift for a logical Alpha node.

Expected ownership comes from scripts/install_launchagents.py:SERVICE_NODE_MAP.
Loaded state comes from launchctl list unless --loaded-file is supplied.
"""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
LAUNCHAGENTS_DIR = REPO_ROOT / "launchagents"
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from install_launchagents import SERVICE_NODE_MAP  # noqa: E402


def label_from_plist_filename(path: Path) -> str:
    name = path.name
    if name.endswith(".template.plist"):
        return name.removesuffix(".template.plist")
    return name.removesuffix(".plist")


def discover_repo_labels(launchagents_dir: Path = LAUNCHAGENTS_DIR) -> set[str]:
    labels: set[str] = set()
    for path in launchagents_dir.glob("*.plist"):
        labels.add(label_from_plist_filename(path))
    return labels


def parse_launchctl_output(text: str) -> set[str]:
    labels: set[str] = set()
    for line in text.splitlines():
        parts = line.split()
        if not parts:
            continue
        label = parts[-1]
        if label.startswith("com.jarvis.alpha."):
            labels.add(label)
    return labels


def loaded_labels_from_launchctl() -> set[str]:
    result = subprocess.run(
        ["launchctl", "list"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "launchctl list failed")
    return parse_launchctl_output(result.stdout)


def infer_node(hostname: str | None = None) -> str:
    host = (hostname or socket.gethostname()).lower()
    if "brain" in host:
        return "brain"
    if "gateway" in host:
        return "gateway"
    if "endpoint" in host:
        return "endpoint"
    if "sandbox" in host:
        return "sandbox"
    raise ValueError(f"cannot infer node from hostname {host!r}; pass --node")


def build_report(
    *,
    node: str,
    repo_labels: Iterable[str],
    loaded_labels: Iterable[str],
    service_node_map: dict[str, str] = SERVICE_NODE_MAP,
) -> dict[str, object]:
    repo_set = set(repo_labels)
    loaded_alpha_set = {
        label for label in loaded_labels if label.startswith("com.jarvis.alpha.")
    }
    expected_set = {
        label
        for label, mapped_node in service_node_map.items()
        if mapped_node == node and label in repo_set
    }
    other_node_repo_labels = {
        label
        for label in repo_set
        if service_node_map.get(label) is not None and service_node_map[label] != node
    }
    unmapped_repo_labels = {
        label
        for label in repo_set
        if label.startswith("com.jarvis.alpha.") and label not in service_node_map
    }
    other_node_loaded = {
        label
        for label in loaded_alpha_set
        if service_node_map.get(label) is not None and service_node_map[label] != node
    }
    unexpected_loaded = loaded_alpha_set - expected_set
    missing_expected = expected_set - loaded_alpha_set

    status = "pass"
    if missing_expected or unexpected_loaded:
        status = "drift"

    return {
        "status": status,
        "node": node,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "repo_total": len(repo_set),
        "loaded_alpha_total": len(loaded_alpha_set),
        "expected_labels": sorted(expected_set),
        "loaded_alpha_labels": sorted(loaded_alpha_set),
        "missing_expected": sorted(missing_expected),
        "unexpected_loaded": sorted(unexpected_loaded),
        "other_node_loaded": sorted(other_node_loaded),
        "other_node_repo_labels": sorted(other_node_repo_labels),
        "unmapped_repo_labels": sorted(unmapped_repo_labels),
    }


def format_report(report: dict[str, object]) -> str:
    lines = [
        f"LaunchAgent drift audit — node={report['node']} status={report['status']}",
        f"checked_at={report['checked_at']}",
        f"repo_total={report['repo_total']} loaded_alpha_total={report['loaded_alpha_total']}",
        "",
    ]
    sections = (
        ("Expected on this node", report["expected_labels"]),
        ("Missing expected", report["missing_expected"]),
        ("Unexpected loaded", report["unexpected_loaded"]),
        ("Other-node repo labels", report["other_node_repo_labels"]),
        ("Unmapped repo labels", report["unmapped_repo_labels"]),
    )
    for title, values in sections:
        lines.append(title + ":")
        if values:
            lines.extend(f"  - {value}" for value in values)
        else:
            lines.append("  - none")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit Alpha LaunchAgent drift")
    parser.add_argument(
        "--node",
        choices=sorted(set(SERVICE_NODE_MAP.values())),
        help="Logical node to audit. Defaults to hostname inference.",
    )
    parser.add_argument(
        "--loaded-file",
        type=Path,
        help="Read launchctl-list-like text from a file instead of running launchctl.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 2 when missing or unexpected labels are found.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        node = args.node or infer_node()
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    repo_labels = discover_repo_labels()
    try:
        if args.loaded_file:
            loaded_labels = parse_launchctl_output(
                args.loaded_file.read_text(encoding="utf-8")
            )
        else:
            loaded_labels = loaded_labels_from_launchctl()
    except Exception as exc:
        print(f"failed to read loaded LaunchAgents: {exc}", file=sys.stderr)
        return 1

    report = build_report(
        node=node,
        repo_labels=repo_labels,
        loaded_labels=loaded_labels,
    )

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(format_report(report), end="")

    if args.strict and report["status"] != "pass":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
