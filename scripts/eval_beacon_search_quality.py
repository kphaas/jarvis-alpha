#!/usr/bin/env python3
"""Run deterministic Beacon search-quality evals."""

from __future__ import annotations

import json
from pathlib import Path
import sys


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root))

    from brain.services.internet_scout.search_quality_evals import (
        run_search_quality_evals,
    )

    results = run_search_quality_evals()
    failed = [result for result in results if not result.passed]
    print(
        json.dumps(
            {
                "status": "failed" if failed else "passed",
                "passed": len(results) - len(failed),
                "failed": len(failed),
                "results": [
                    {
                        "name": result.name,
                        "passed": result.passed,
                        "details": result.details,
                        "failures": list(result.failures),
                    }
                    for result in results
                ],
            },
            sort_keys=True,
        )
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
