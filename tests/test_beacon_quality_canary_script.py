from __future__ import annotations

import importlib.util
from pathlib import Path
from urllib.parse import unquote, urlsplit


def _load_script_module():
    path = Path(__file__).resolve().parents[1] / "scripts/run_beacon_quality_canary.py"
    spec = importlib.util.spec_from_file_location("run_beacon_quality_canary", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_quality_canary_runner_injects_writer_password(monkeypatch) -> None:
    monkeypatch.setenv(
        "ALPHA_DB_DSN_WRITER",
        "postgresql://jarvis_alpha_writer@localhost:5432/jarvis_alpha",
    )
    monkeypatch.setenv("ALPHA_WRITER_DB_PASSWORD", "writer password")

    module = _load_script_module()

    parsed = urlsplit(module._writer_dsn())
    assert parsed.username == "jarvis_alpha_writer"
    assert unquote(parsed.password or "") == "writer password"
    assert parsed.hostname == "localhost"
    assert parsed.port == 5432
    assert parsed.path == "/jarvis_alpha"
