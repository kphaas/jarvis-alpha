from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("ALPHA_DB_DSN", "postgresql://localhost/db")
os.environ.setdefault("ALPHA_DB_DSN_WRITER", "postgresql://localhost/db")
os.environ.setdefault("ALPHA_DB_DSN_BUDDY", "postgresql://localhost/db")
os.environ.setdefault("ALPHA_GATEWAY_URL", "https://localhost:8283")

from fastapi import FastAPI
from fastapi.testclient import TestClient

import brain.routes.health as health
from brain.middleware.approval_classes import ROUTE_CLASSIFICATION


def _client(monkeypatch, report_path: Path) -> TestClient:
    monkeypatch.setenv("JARVIS_MAINTAINER_REPORT_PATH", str(report_path))
    app = FastAPI()
    app.include_router(health.router)
    return TestClient(app)


def test_maintainer_health_reads_local_report(tmp_path, monkeypatch):
    report_path = tmp_path / "maintainer_report.json"
    last_scan_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    report_path.write_text(
        json.dumps(
            {
                "authority": "none",
                "candidates": [
                    {
                        "id": "MNT-0001",
                        "node": "brain",
                        "layer": "python",
                        "package": "fastapi",
                        "from_ver": "1.0.0",
                        "to_ver": "1.0.1",
                        "semver_delta": "patch",
                        "tier": "T-patch",
                        "state": "DETECTED",
                        "detected_at": last_scan_at,
                    }
                ],
                "candidate_count": 2,
                "candidate_count_by_tier": {"T-patch": 1, "T-minor": 1},
                "drift_count": 1,
                "inventory_count": 5,
                "inventory_rows_recorded": 3,
                "last_scan_at": last_scan_at,
                "new_or_existing_candidate_ids": ["MNT-0001", "MNT-0002"],
                "node": "brain",
            }
        )
    )

    body = _client(monkeypatch, report_path).get("/v1/health/maintainer").json()

    assert body["status"] == "ok"
    assert body["source"] == "jarvis-maintainer"
    assert body["authority"] == "none"
    assert body["candidate_count"] == 2
    assert body["candidate_count_by_tier"] == {"T-patch": 1, "T-minor": 1}
    assert body["candidates"][0]["id"] == "MNT-0001"
    assert body["candidates"][0]["package"] == "fastapi"
    assert body["drift_count"] == 1
    assert body["inventory_count"] == 5
    assert body["inventory_rows_recorded"] == 3
    assert body["new_or_existing_candidate_ids"] == ["MNT-0001", "MNT-0002"]
    assert body["is_stale"] is False
    assert body["scan_age_hours"] is not None
    assert body["scan_stale_after_hours"] == 24
    assert body["node"] == "brain"
    assert body["path"] == str(report_path)


def test_maintainer_health_missing_report_is_displayable(tmp_path, monkeypatch):
    report_path = tmp_path / "missing.json"
    response = _client(monkeypatch, report_path).get("/v1/health/maintainer")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "missing"
    assert body["candidate_count"] == 0
    assert body["candidates"] == []
    assert body["authority"] == "none"
    assert body["is_stale"] is False


def test_maintainer_health_invalid_report_is_displayable(tmp_path, monkeypatch):
    report_path = tmp_path / "bad.json"
    report_path.write_text("not-json")

    response = _client(monkeypatch, report_path).get("/v1/health/maintainer")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "invalid"
    assert "invalid json" in body["error"]


def test_maintainer_health_marks_old_scan_stale(tmp_path, monkeypatch):
    report_path = tmp_path / "maintainer_report.json"
    report_path.write_text(
        json.dumps(
            {
                "authority": "none",
                "candidate_count": 0,
                "last_scan_at": "2000-01-01 00:00:00",
                "node": "brain",
            }
        )
    )

    body = _client(monkeypatch, report_path).get("/v1/health/maintainer").json()

    assert body["status"] == "stale"
    assert body["is_stale"] is True
    assert body["scan_age_hours"] > 24


def test_maintainer_health_route_is_read_only_classified():
    assert ROUTE_CLASSIFICATION["GET /v1/health/maintainer"] == [
        "read",
        "security_read",
    ]
