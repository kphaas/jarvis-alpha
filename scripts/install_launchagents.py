#!/usr/bin/env python3
"""
install_launchagents.py — render launchd plist templates to ~/Library/LaunchAgents/

Reads *.template.plist files from the repo's launchagents/ directory, substitutes
placeholders ({{HOME}}, optionally {{USER}}) with the current user's values,
and writes the rendered plists to ~/Library/LaunchAgents/.

Why this exists:
  Plists in git must NOT contain user-specific paths. Deployment across machines
  with different macOS usernames (jarvisbrain, infranet, jarvissand, jarvisendpoint)
  requires substitution at install time. This is the standard Helm/Kustomize
  pattern applied to launchd.

Usage:
  python3 scripts/install_launchagents.py                       # auto-detect
  python3 scripts/install_launchagents.py --node gateway        # only gateway plists
  python3 scripts/install_launchagents.py --home /Users/gate    # override HOME
  python3 scripts/install_launchagents.py --dry-run             # print, don't write
  python3 scripts/install_launchagents.py --list                # show discovered templates

Exit codes:
  0  success
  1  usage error or unrecoverable error
  2  one or more templates failed to render
"""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = REPO_ROOT / "launchagents"
PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Z_][A-Z0-9_]*)\s*\}\}")

SERVICE_NODE_MAP = {
    "com.jarvis.alpha.gateway": "gateway",
    "com.jarvis.alpha.power.gateway": "gateway",
    "com.jarvis.alpha.rotate.gateway": "gateway",
    "com.jarvis.alpha.at0-mail": "brain",
    "com.jarvis.alpha.at0-mail-health": "brain",
    "com.jarvis.alpha.ai-news-brief": "brain",
    "com.jarvis.alpha.market-brief": "brain",
    "com.jarvis.alpha.brain": "brain",
    "com.jarvis.alpha.buddy": "brain",
    "com.jarvis.alpha.beacon-quality": "brain",
    "com.jarvis.alpha.executor": "brain",
    "com.jarvis.alpha.fluentbit": "brain",
    "com.jarvis.alpha.gmail-health": "brain",
    "com.jarvis.alpha.herald-linkedin-engagement-scheduler": "brain",
    "com.jarvis.alpha.herald-linkedin-health": "brain",
    "com.jarvis.alpha.herald-linkedin-target-scout": "brain",
    "com.jarvis.alpha.herald-linkedin-weekly-draft": "brain",
    "com.jarvis.alpha.loki": "brain",
    "com.jarvis.alpha.memory-observability": "brain",
    "com.jarvis.alpha.pg_backup": "brain",
    "com.jarvis.alpha.power.brain": "brain",
    "com.jarvis.alpha.rotate.brain_service": "brain",
    "com.jarvis.alpha.rotate.buddy": "brain",
    "com.jarvis.alpha.school-email": "brain",
    "com.jarvis.alpha.spark-send-readiness": "brain",
    "com.jarvis.alpha.sweep-cert-renewal.brain": "brain",
    "com.jarvis.alpha.sweep-cert-renewal.endpoint": "endpoint",
    "com.jarvis.alpha.sweep-cert-renewal.gateway": "gateway",
    "com.jarvis.alpha.sweep-cert-renewal.sandbox": "sandbox",
    "com.jarvis.alpha.temporal.server": "brain",
    "com.jarvis.alpha.temporal.ui": "brain",
    "com.jarvis.alpha.temporal.worker": "brain",
    "com.jarvis.alpha.watchdog": "brain",
    "com.jarvis.alpha.power.endpoint": "endpoint",
    "com.jarvis.alpha.rotate.endpoint": "endpoint",
    "com.jarvis.alpha.power.sandbox": "sandbox",
    "com.jarvis.alpha.restore_drill": "sandbox",
    "com.jarvis.alpha.rotate.sandbox": "sandbox",
}


def log(level, message, **extra):
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "service": "install_launchagents",
        "node": os.environ.get("JARVIS_NODE", "unknown"),
        "message": message,
    }
    record.update(extra)
    print(json.dumps(record), file=sys.stderr if level == "error" else sys.stdout)


def discover_templates():
    if not TEMPLATES_DIR.is_dir():
        raise FileNotFoundError(f"launchagents/ not found at {TEMPLATES_DIR}")
    return sorted(TEMPLATES_DIR.glob("*.template.plist"))


def find_placeholders(content):
    return set(PLACEHOLDER_RE.findall(content))


def render(template_path, values):
    content = template_path.read_text()
    placeholders = find_placeholders(content)
    missing = placeholders - values.keys()
    if missing:
        raise ValueError(
            f"{template_path.name} uses placeholders {sorted(missing)} "
            f"but no value provided"
        )

    def repl(match):
        return values[match.group(1)]

    rendered = PLACEHOLDER_RE.sub(repl, content)

    try:
        plistlib.loads(rendered.encode("utf-8"))
    except Exception as e:
        raise ValueError(f"{template_path.name} rendered to invalid plist: {e}")

    target_name = template_path.name.replace(".template.plist", ".plist")
    return rendered, target_name


def filter_by_node(templates, node):
    out = []
    for t in templates:
        label = t.name.replace(".template.plist", "")
        mapped_node = SERVICE_NODE_MAP.get(label)
        if mapped_node is None:
            log(
                "warn",
                "template not in SERVICE_NODE_MAP, skipping",
                template=t.name,
                node_requested=node,
            )
            continue
        if mapped_node == node:
            out.append(t)
    return out


def parse_args():
    parser = argparse.ArgumentParser(
        description="Render launchd plist templates for current user",
    )
    parser.add_argument(
        "--home",
        default=os.environ.get("HOME"),
        help="Home directory to substitute for {{HOME}} (default: $HOME)",
    )
    parser.add_argument(
        "--user",
        default=os.environ.get("USER"),
        help="Username to substitute for {{USER}} (default: $USER)",
    )
    parser.add_argument(
        "--node",
        choices=sorted(set(SERVICE_NODE_MAP.values())),
        help="Only install plists for a specific logical node",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print rendered output to stdout, do not write files",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List discovered templates and their target filenames, exit",
    )
    parser.add_argument(
        "--output-dir",
        default=str(Path.home() / "Library" / "LaunchAgents"),
        help="Override target directory (default: ~/Library/LaunchAgents)",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    if not args.home:
        log("error", "--home not set and $HOME is empty")
        return 1
    if not args.user:
        log("error", "--user not set and $USER is empty")
        return 1

    values = {"HOME": args.home, "USER": args.user}

    try:
        templates = discover_templates()
    except FileNotFoundError as e:
        log("error", str(e))
        return 1

    if args.node:
        templates = filter_by_node(templates, args.node)

    if not templates:
        log(
            "warn",
            "no templates found matching criteria",
            node=args.node,
            templates_dir=str(TEMPLATES_DIR),
        )
        return 0

    if args.list:
        for t in templates:
            target = t.name.replace(".template.plist", ".plist")
            print(f"{t.name}  ->  {target}")
        return 0

    output_dir = Path(args.output_dir)
    if not args.dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)

    errors = 0
    for template_path in templates:
        try:
            rendered, target_name = render(template_path, values)
        except ValueError as e:
            log("error", "render failed", template=template_path.name, error=str(e))
            errors += 1
            continue

        if args.dry_run:
            print(f"--- {target_name} ---")
            print(rendered)
            print()
            continue

        target_path = output_dir / target_name
        target_path.write_text(rendered)
        log("info", "installed", template=template_path.name, target=str(target_path))

    if errors:
        log("error", f"{errors} template(s) failed to render")
        return 2

    log(
        "info",
        "install complete",
        count=len(templates),
        home=args.home,
        user=args.user,
        output_dir=str(output_dir),
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
