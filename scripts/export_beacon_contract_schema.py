#!/usr/bin/env python3
"""Export Beacon contracts shared with Helm."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import TypeAlias

from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_DIR = REPO_ROOT / "docs" / "contracts"

ModelType: TypeAlias = type[BaseModel]


def _contracts() -> dict[str, ModelType]:
    sys.path.insert(0, str(REPO_ROOT))
    sys.path.insert(0, str(REPO_ROOT / "common"))
    from brain.routes.helm import HelmBeaconSummary
    from brain.services.internet_scout.models import InternetScoutResearchReport

    return {
        "beacon_helm_summary.schema.json": HelmBeaconSummary,
        "beacon_research_report.schema.json": InternetScoutResearchReport,
    }


def _render_schema(model: ModelType) -> str:
    payload = model.model_json_schema()
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def export_contracts(*, check: bool) -> int:
    CONTRACT_DIR.mkdir(parents=True, exist_ok=True)
    drifted: list[str] = []
    for filename, model in _contracts().items():
        path = CONTRACT_DIR / filename
        rendered = _render_schema(model)
        if check:
            existing = path.read_text(encoding="utf-8") if path.exists() else ""
            if existing != rendered:
                drifted.append(filename)
            continue
        path.write_text(rendered, encoding="utf-8")

    if drifted:
        print(
            json.dumps(
                {
                    "status": "drifted",
                    "contracts": drifted,
                },
                sort_keys=True,
            )
        )
        return 1
    print(
        json.dumps(
            {
                "status": "ok",
                "contracts": sorted(_contracts()),
            },
            sort_keys=True,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    return export_contracts(check=args.check)


if __name__ == "__main__":
    sys.exit(main())
