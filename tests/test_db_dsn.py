from urllib.parse import urlsplit, unquote

from brain.db.dsn import ensure_writer_password


def test_ensure_writer_password_injects_password_for_writer_dsn(monkeypatch):
    monkeypatch.setenv("ALPHA_WRITER_DB_PASSWORD", "p@ss:word/with symbols")

    dsn = ensure_writer_password(
        "postgresql://jarvis_alpha_writer@127.0.0.1:5432/jarvis_alpha"
    )

    parsed = urlsplit(dsn)
    assert parsed.username == "jarvis_alpha_writer"
    assert unquote(parsed.password or "") == "p@ss:word/with symbols"
    assert parsed.hostname == "127.0.0.1"
    assert parsed.port == 5432
    assert parsed.path == "/jarvis_alpha"


def test_ensure_writer_password_preserves_existing_password(monkeypatch):
    monkeypatch.setenv("ALPHA_WRITER_DB_PASSWORD", "replacement")

    dsn = ensure_writer_password(
        "postgresql://jarvis_alpha_writer:existing@localhost/jarvis_alpha"
    )

    assert dsn == "postgresql://jarvis_alpha_writer:existing@localhost/jarvis_alpha"


def test_ensure_writer_password_leaves_non_writer_dsn_alone(monkeypatch):
    monkeypatch.setenv("ALPHA_WRITER_DB_PASSWORD", "writer-password")

    dsn = ensure_writer_password("postgresql://jarvisbrain@localhost/jarvis_alpha")

    assert dsn == "postgresql://jarvisbrain@localhost/jarvis_alpha"


def test_ensure_writer_password_strips_secret_file_quotes(monkeypatch):
    monkeypatch.setenv("ALPHA_WRITER_DB_PASSWORD", '"quoted-password"')

    dsn = ensure_writer_password(
        "'postgresql://jarvis_alpha_writer@localhost/jarvis_alpha'"
    )

    parsed = urlsplit(dsn)
    assert parsed.password == "quoted-password"
