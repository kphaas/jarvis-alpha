from brain.audit import secret_audit


def test_secret_audit_runtime_uses_append_function():
    assert "public.record_secret_access" in secret_audit.INSERT_SQL
    assert "INSERT INTO secret_access_log" not in secret_audit.INSERT_SQL


def test_secret_audit_readiness_is_read_only():
    assert "CREATE TABLE" not in secret_audit.READINESS_SQL
    assert "CREATE INDEX" not in secret_audit.READINESS_SQL
    assert "has_function_privilege" in secret_audit.READINESS_SQL
