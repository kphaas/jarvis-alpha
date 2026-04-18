#!/usr/bin/env python3
"""
render_events.py — Stream filter for jarvisalpha_pull.sh structured events.

Reads stdin line by line. Lines prefixed with ##EVT## are parsed as JSON
events and rendered as pretty status lines. Non-event lines pass through
only if VERBOSE >= 1.

On any event with status=fail, prints the rendered line, emits
##RENDER_FAIL##<json> on stdout (for bash to trigger failure box), and
exits 1 after stream ends.

Exit codes:
  0 — all events ok
  1 — one or more events failed
  2 — parse error on event JSON
"""

import argparse
import json
import os
import sys


# ── ANSI colors (respect NO_COLOR env var) ───────────────
USE_COLOR = os.isatty(1) and os.environ.get("NO_COLOR", "") == ""
GREEN = "\033[0;32m" if USE_COLOR else ""
RED = "\033[0;31m" if USE_COLOR else ""
YELLOW = "\033[1;33m" if USE_COLOR else ""
DIM = "\033[2m" if USE_COLOR else ""
RESET = "\033[0m" if USE_COLOR else ""


def fmt_duration(ms):
    """Format milliseconds as human-readable duration. Right-aligned 6 chars."""
    if ms is None:
        return " " * 6
    seconds = ms / 1000.0
    if seconds < 10:
        return f"{seconds:>5.2f}s"
    elif seconds < 60:
        return f"{seconds:>5.1f}s"
    else:
        m = int(seconds // 60)
        s = int(seconds % 60)
        return f"{m:>2}m{s:02}s"


def icon(status):
    if status == "ok":
        return f"{GREEN}✅{RESET}"
    elif status == "fail":
        return f"{RED}❌{RESET}"
    elif status == "skip":
        return f"{DIM}—{RESET} "
    else:
        return f"{YELLOW}⚠️ {RESET}"


def render_event(evt):
    """
    Render a single event to a formatted line.
    Format: "  {icon} {step_name:<22} {detail:<40} {duration:>7}"
    """
    status = evt.get("status", "unknown")
    phase = evt.get("phase", "unknown")
    dur = fmt_duration(evt.get("dur_ms"))
    st_icon = icon(status)

    # Per-phase rendering
    if phase == "pull":
        from_h = evt.get("from_hash", "none")
        to_h = evt.get("to_hash", "unknown")
        fc = evt.get("file_count", 0)
        if from_h == to_h:
            detail = f"already up to date ({to_h})"
        else:
            detail = f"{from_h} → {to_h} · {fc} file{'s' if fc != 1 else ''}"
        step = "git pull"

    elif phase == "migration":
        if status == "skip":
            step = "migrations"
            detail = f"{DIM}(not applicable this node){RESET}"
        elif status == "fail":
            step = "migrations"
            detail = evt.get("error", "unknown error")[:60]
        else:
            applied = evt.get("applied", 0)
            skipped = evt.get("skipped", 0)
            failed = evt.get("failed", 0)
            step = "migrations"
            detail = f"applied {applied} · skipped {skipped} · failed {failed}"

    elif phase == "pycache":
        node = evt.get("node", "")
        step = "clear __pycache__"
        detail = f"{node}/ cleaned"

    elif phase == "restart":
        service = evt.get("service", "unknown")
        pid = evt.get("pid", 0)
        step = f"restart {service}"
        if status == "skip":
            reason = evt.get("reason", "skipped").replace("_", " ")
            detail = f"{DIM}skipped — {reason}{RESET}"
        elif status == "fail":
            detail = evt.get("error", "launchagent load failed")[:60]
        elif pid and pid != 0:
            detail = f"launchagent loaded · pid {pid}"
        else:
            detail = "launchagent loaded"

    elif phase == "health":
        url = evt.get("url", "")
        # Shorten URL: strip protocol + port for display
        url_short = url.replace("https://", "").replace("http://", "")
        code = evt.get("http_code", 0)
        step = "health check"
        if status == "fail":
            detail = f"{url_short} · {evt.get('error', 'failed')[:40]}"
        else:
            detail = f"{url_short} {code}"

    elif phase == "tests":
        passed = evt.get("passed", 0)
        failed = evt.get("failed", 0)
        step = "test gate"
        if status == "skip":
            reason = evt.get("reason", "skipped").replace("_", " ")
            detail = f"{DIM}skipped — {reason}{RESET}"
        elif status == "fail":
            detail = evt.get("error", "tests failed")[:60]
        else:
            detail = f"{passed} passed · {failed} failed"

    elif phase == "dist_check":
        fc = evt.get("file_count", 0)
        step = "ui/dist verified"
        if status == "fail":
            detail = evt.get("error", "missing")[:60]
        else:
            detail = f"{fc} files present"

    elif phase == "complete":
        # Don't render — the node footer uses total_dur_ms separately
        return None

    else:
        step = phase
        detail = evt.get("error", "") if status == "fail" else "ok"

    return f"  {st_icon} {step:<22} {detail:<45} {dur}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--node",
        default="",
        help="Node name (for prefixing; currently informational only)",
    )
    parser.add_argument(
        "--verbose",
        type=int,
        default=int(os.environ.get("VERBOSE", "0")),
        help="Verbosity level (0 = events only, 1 = +human lines, 2 = +raw JSON)",
    )
    args = parser.parse_args()

    any_fail = False
    total_dur_ms = None

    for raw_line in sys.stdin:
        line = raw_line.rstrip("\n")

        # Event line
        if line.startswith("##EVT##"):
            json_str = line[len("##EVT##") :]
            try:
                evt = json.loads(json_str)
            except json.JSONDecodeError as e:
                print(
                    f"{RED}!! render_events.py: parse error: {e}{RESET}",
                    file=sys.stderr,
                )
                print(f"   Raw: {json_str}", file=sys.stderr)
                sys.exit(2)

            # Verbose level 2: show raw JSON too
            if args.verbose >= 2:
                print(f"{DIM}  # {json_str}{RESET}")

            # Track total duration from complete event
            if evt.get("phase") == "complete":
                total_dur_ms = evt.get("total_dur_ms")

            # Render event
            rendered = render_event(evt)
            if rendered is not None:
                print(rendered)
                sys.stdout.flush()

            # Track failures + emit sentinel for bash to detect
            if evt.get("status") == "fail":
                any_fail = True
                print(f"##RENDER_FAIL##{json_str}")
                sys.stdout.flush()

        # Human output line (no event prefix)
        else:
            if args.verbose >= 1:
                # Pass through, dim-prefixed so it's clearly raw output
                print(f"{DIM}    {line}{RESET}")
                sys.stdout.flush()
            # else: drop silently in NORMAL mode

    # Emit terminal sentinel for bash to pick up node duration
    if total_dur_ms is not None:
        print(f"##RENDER_DONE##{total_dur_ms}")

    sys.exit(1 if any_fail else 0)


if __name__ == "__main__":
    main()
