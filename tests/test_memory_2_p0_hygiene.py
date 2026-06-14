from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_memory_service_no_longer_carries_dead_promotion_thresholds() -> None:
    source = (ROOT / "brain" / "memory" / "memory.py").read_text(encoding="utf-8")

    assert "PROMOTION_SCORE_THRESHOLD" not in source
    assert "PROMOTION_ACCESS_THRESHOLD" not in source


def test_memory_vectors_are_explicitly_split_by_domain() -> None:
    memory_migration = (
        ROOT / "brain" / "db" / "migrations" / "004_vector_768.sql"
    ).read_text(encoding="utf-8")
    schema = (ROOT / "brain" / "db" / "schema.sql").read_text(encoding="utf-8")

    assert "ALTER COLUMN embedding TYPE vector(768)" in memory_migration
    assert "embedding       vector(384)" in schema
    assert "CREATE TABLE vault_chunks" in schema
