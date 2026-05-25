from scripts.check_duplicate_config_drift import find_duplicate_config_drift


def test_duplicate_config_drift_guard_allows_identical_duplicates(tmp_path):
    first = tmp_path / "launchagents" / "com.jarvis.alpha.example.plist"
    second = tmp_path / "archive" / "com.jarvis.alpha.example.plist"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_text("<plist><dict /></plist>\n", encoding="utf-8")
    second.write_text("<plist><dict /></plist>\n", encoding="utf-8")

    assert find_duplicate_config_drift(tmp_path) == []


def test_duplicate_config_drift_guard_flags_divergent_duplicates(tmp_path):
    first = tmp_path / "endpoint" / "alpha.conf"
    second = tmp_path / "scripts" / "alpha.conf"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_text("server { listen 4100; }\n", encoding="utf-8")
    second.write_text("server { listen 8186; }\n", encoding="utf-8")

    drifts = find_duplicate_config_drift(tmp_path)

    assert len(drifts) == 1
    assert drifts[0].basename == "alpha.conf"
    assert drifts[0].paths == (
        first.relative_to(tmp_path),
        second.relative_to(tmp_path),
    )


def test_duplicate_config_drift_guard_ignores_non_config_files(tmp_path):
    first = tmp_path / "docs" / "README.md"
    second = tmp_path / "other" / "README.md"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_text("one\n", encoding="utf-8")
    second.write_text("two\n", encoding="utf-8")

    assert find_duplicate_config_drift(tmp_path) == []
