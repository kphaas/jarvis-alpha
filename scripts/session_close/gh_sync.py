#!/usr/bin/env python3
"""
GitHub Issues sync tool for session close.

Reads a JSON manifest describing labels to ensure, issues to close, issues to
create-and-close (audit-trail pattern), and new issues to create open.

Usage:
    python3 gh_sync.py --manifest manifests/2026-04-18.json              # DRY RUN
    python3 gh_sync.py --manifest manifests/2026-04-18.json --execute    # LIVE
    python3 gh_sync.py --manifest manifests/2026-04-18.json --execute --skip-existing

Exit codes:
    0 - success (dry or live)
    1 - halted mid-execution (error from gh)
    2 - manifest validation failed
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime


def load_manifest(path: Path) -> dict:
    if not path.exists():
        print(f"❌ Manifest not found: {path}", file=sys.stderr)
        sys.exit(2)
    try:
        with open(path) as f:
            manifest = json.load(f)
    except json.JSONDecodeError as e:
        print(f"❌ Manifest JSON invalid: {e}", file=sys.stderr)
        sys.exit(2)
    required_keys = {
        "session_date",
        "labels_to_ensure",
        "close_existing",
        "create_and_close",
        "create_open",
    }
    missing = required_keys - set(manifest.keys())
    if missing:
        print(f"❌ Manifest missing keys: {missing}", file=sys.stderr)
        sys.exit(2)
    return manifest


def gh_call(args: list, execute: bool, log_file) -> tuple[int, str]:
    """Run a gh command. Returns (returncode, stdout). Logs to log_file."""
    cmd = ["gh"] + args
    cmd_str = " ".join(f"'{a}'" if " " in a else a for a in cmd)
    log_file.write(f"\n--- {datetime.now().isoformat()} ---\n")
    log_file.write(f"CMD: {cmd_str}\n")
    if not execute:
        log_file.write("MODE: DRY\n")
        print(f"  DRY: {cmd[0]} {cmd[1]} {cmd[2]} ...")
        return 0, ""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        log_file.write(f"EXIT: {result.returncode}\n")
        log_file.write(f"STDOUT: {result.stdout}\n")
        log_file.write(f"STDERR: {result.stderr}\n")
        if result.returncode != 0:
            print(f"  ❌ gh failed (exit {result.returncode})")
            print(f"     {result.stderr.strip()[:200]}")
        return result.returncode, result.stdout.strip()
    except subprocess.TimeoutExpired:
        log_file.write("EXIT: TIMEOUT\n")
        print("  ❌ gh timeout after 30s")
        return 124, ""


def find_existing_issue(title: str, execute: bool, log_file) -> int | None:
    """Search for an existing issue by exact title. Returns issue number or None."""
    if not execute:
        return None
    rc, stdout = gh_call(
        [
            "issue",
            "list",
            "--state",
            "all",
            "--search",
            title,
            "--json",
            "number,title",
            "--limit",
            "5",
        ],
        execute,
        log_file,
    )
    if rc != 0 or not stdout:
        return None
    try:
        issues = json.loads(stdout)
        for issue in issues:
            if issue["title"] == title:
                return issue["number"]
    except json.JSONDecodeError:
        pass
    return None


def stage_labels(manifest: dict, execute: bool, log_file) -> int:
    """Ensure labels exist. --force makes gh label create idempotent."""
    print("── Stage A — Ensure labels ─────────────────────────────")
    count = 0
    for label in manifest["labels_to_ensure"]:
        rc, _ = gh_call(
            [
                "label",
                "create",
                label["name"],
                "--color",
                label["color"],
                "--description",
                label.get("description", ""),
                "--force",
            ],
            execute,
            log_file,
        )
        if rc != 0:
            return count
        print(f"  ✅ label: {label['name']}")
        count += 1
    return count


def stage_close_existing(manifest: dict, execute: bool, log_file) -> int:
    """Close issues that already exist in GitHub."""
    print("── Stage B — Close existing issues ─────────────────────")
    count = 0
    for item in manifest["close_existing"]:
        issue_num = item["issue_number"]
        td = item["td_id"]
        comment = item["comment"]
        print(f"  Closing #{issue_num} ({td})...")
        rc, _ = gh_call(
            ["issue", "close", str(issue_num), "--comment", comment], execute, log_file
        )
        if rc != 0:
            print(f"  ❌ Halted at {td} (issue #{issue_num})")
            return count
        print(f"  ✅ closed #{issue_num}")
        count += 1
    return count


def stage_create_and_close(
    manifest: dict, execute: bool, log_file, skip_existing: bool
) -> int:
    """Create issue + immediately close (audit-trail pattern)."""
    print("── Stage C — Create + close (audit trail) ──────────────")
    count = 0
    for item in manifest["create_and_close"]:
        td = item["td_id"]
        title = item["title"]
        if skip_existing:
            existing = find_existing_issue(title, execute, log_file)
            if existing:
                print(f"  ⏭  {td} already exists as #{existing} — skipping")
                continue
        print(f"  Creating {td}...")
        rc, stdout = gh_call(
            [
                "issue",
                "create",
                "--title",
                title,
                "--body",
                item["body"],
                "--label",
                ",".join(item["labels"]),
            ],
            execute,
            log_file,
        )
        if rc != 0:
            print(f"  ❌ Halted creating {td}")
            return count
        # Extract issue number from URL output
        if execute:
            issue_num = stdout.strip().split("/")[-1]
            print(f"  ✅ created {td} as #{issue_num}")
            rc, _ = gh_call(
                ["issue", "close", issue_num, "--comment", item["close_comment"]],
                execute,
                log_file,
            )
            if rc != 0:
                print(
                    f"  ❌ Halted closing {td} (#{issue_num}) — created but not closed"
                )
                return count
            print(f"  ✅ closed #{issue_num}")
        else:
            print(f"  DRY: would create + close {td}")
        count += 1
    return count


def stage_create_open(
    manifest: dict, execute: bool, log_file, skip_existing: bool
) -> int:
    """Create new open issues."""
    print("── Stage D — Create open issues ────────────────────────")
    count = 0
    for item in manifest["create_open"]:
        td = item["td_id"]
        title = item["title"]
        if skip_existing:
            existing = find_existing_issue(title, execute, log_file)
            if existing:
                print(f"  ⏭  {td} already exists as #{existing} — skipping")
                continue
        print(f"  Creating {td}...")
        rc, stdout = gh_call(
            [
                "issue",
                "create",
                "--title",
                title,
                "--body",
                item["body"],
                "--label",
                ",".join(item["labels"]),
            ],
            execute,
            log_file,
        )
        if rc != 0:
            print(f"  ❌ Halted creating {td}")
            return count
        if execute:
            issue_num = stdout.strip().split("/")[-1]
            print(f"  ✅ created {td} as #{issue_num}")
        else:
            print(f"  DRY: would create {td}")
        count += 1
    return count


def main():
    parser = argparse.ArgumentParser(description="GitHub Issues sync for session close")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument(
        "--execute", action="store_true", help="Actually call gh (default: dry-run)"
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Check for existing issue by title before creating",
    )
    args = parser.parse_args()

    manifest = load_manifest(args.manifest)
    session_date = manifest["session_date"]
    log_path = Path(f"/tmp/gh_sync_{session_date}.log")

    print(f"═══ {'LIVE' if args.execute else 'DRY RUN'} MODE ═══")
    print(f"Session: {session_date}")
    print(f"Manifest: {args.manifest}")
    print(f"Log: {log_path}")
    print()

    with open(log_path, "w") as log_file:
        log_file.write(f"gh_sync run {datetime.now().isoformat()}\n")
        log_file.write(f"Manifest: {args.manifest}\n")
        log_file.write(f"Execute: {args.execute}\n")
        log_file.write(f"Skip-existing: {args.skip_existing}\n")

        counts = {"labels": 0, "closed": 0, "created_closed": 0, "created_open": 0}
        halted = False

        counts["labels"] = stage_labels(manifest, args.execute, log_file)
        if counts["labels"] < len(manifest["labels_to_ensure"]):
            halted = True
        print()

        if not halted:
            counts["closed"] = stage_close_existing(manifest, args.execute, log_file)
            if counts["closed"] < len(manifest["close_existing"]):
                halted = True
            print()

        if not halted:
            counts["created_closed"] = stage_create_and_close(
                manifest, args.execute, log_file, args.skip_existing
            )
            if counts["created_closed"] < len(manifest["create_and_close"]):
                halted = True
            print()

        if not halted:
            counts["created_open"] = stage_create_open(
                manifest, args.execute, log_file, args.skip_existing
            )
            if counts["created_open"] < len(manifest["create_open"]):
                halted = True
            print()

    print("═══ SUMMARY ═══")
    print(
        f"  Labels ensured:       {counts['labels']}/{len(manifest['labels_to_ensure'])}"
    )
    print(
        f"  Existing closed:      {counts['closed']}/{len(manifest['close_existing'])}"
    )
    print(
        f"  Created + closed:     {counts['created_closed']}/{len(manifest['create_and_close'])}"
    )
    print(
        f"  New open created:     {counts['created_open']}/{len(manifest['create_open'])}"
    )
    print(f"  Log: {log_path}")

    if halted:
        print()
        print(
            "⚠️  HALTED mid-run. Review log, fix issue, re-run with --skip-existing to resume."
        )
        sys.exit(1)
    if not args.execute:
        print()
        print(f"To execute: python3 {sys.argv[0]} --manifest {args.manifest} --execute")
    sys.exit(0)


if __name__ == "__main__":
    main()
