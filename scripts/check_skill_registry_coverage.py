#!/usr/bin/env python3
"""Fail fast when active skill registry entries drift from handlers."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for path in (REPO_ROOT / "common", REPO_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def main() -> int:
    from brain.registry.catalog import INITIAL_SKILLS
    from brain.registry.drift import assert_skill_handler_coverage
    from brain.skills.handlers import all_skill_handlers

    assert_skill_handler_coverage(INITIAL_SKILLS, all_skill_handlers())
    print("skill registry coverage OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
