from datetime import datetime, timezone

from brain.services.temporal_storage_monitor import (
    _build_snapshot_payload,
    _format_bytes,
    _status_for_snapshot,
    temporal_storage_summary_body,
)


def test_format_bytes_uses_binary_units():
    assert _format_bytes(1023) == "1023 B"
    assert _format_bytes(1024) == "1.0 KiB"
    assert _format_bytes(1024 * 1024 * 3) == "3.0 MiB"


def test_status_alert_wins_over_degraded():
    assert (
        _status_for_snapshot(errors=["row count failed"], threshold_exceeded=True)
        == "alert"
    )


def test_build_snapshot_payload_alerts_at_free_disk_fraction():
    payload = _build_snapshot_payload(
        checked_at=datetime(2026, 5, 25, tzinfo=timezone.utc),
        disk_path="/",
        disk_total_bytes=1_000,
        disk_free_bytes=100,
        databases=[
            {
                "name": "temporal",
                "size_bytes": 76,
                "size_pretty": "76 B",
                "row_counts": {"history_node": 12},
                "error": None,
            }
        ],
        errors=[],
        alert_free_fraction=0.75,
    )

    assert payload["status"] == "alert"
    assert payload["threshold_bytes"] == 75
    assert payload["threshold_exceeded"] is True
    assert payload["temporal_total_bytes"] == 76


def test_temporal_storage_summary_body_includes_core_counts():
    snapshot = {
        "temporal_total_pretty": "20.0 MiB",
        "disk_free_pretty": "100.0 GiB",
        "threshold_pretty": "75.0 GiB",
        "databases": [
            {
                "name": "temporal",
                "size_pretty": "10.0 MiB",
                "row_counts": {"history_node": 5},
            },
            {
                "name": "temporal_visibility",
                "size_pretty": "10.0 MiB",
                "row_counts": {"executions_visibility": 3},
            },
        ],
        "errors": [],
    }

    body = temporal_storage_summary_body(snapshot)

    assert "Temporal total 20.0 MiB" in body
    assert "history_node=5" in body
    assert "executions_visibility=3" in body
