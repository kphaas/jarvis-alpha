from pathlib import Path


def test_db_baselines_do_not_commit_role_password_hashes():
    baseline_dir = Path("db/baselines")
    for path in baseline_dir.glob("*.sql"):
        text = path.read_text(encoding="utf-8")
        assert "SCRAM-SHA-256" not in text
        assert " PASSWORD '" not in text
