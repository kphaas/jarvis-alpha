#!/usr/bin/env python3
"""Run deterministic Beacon search-quality evals."""

from __future__ import annotations

import json
from pathlib import Path
import sys


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root))

    from brain.services.internet_scout.quality_canary import (
        search_quality_eval_payload,
    )

    payload = search_quality_eval_payload()
    print(
        json.dumps(
            payload,
            sort_keys=True,
        )
    )
    return 1 if payload["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
