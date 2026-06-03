from datetime import datetime, timezone

from scripts import sweep_tls_cert_renewal as sweep


def test_parse_openssl_time_reads_gmt_dates():
    parsed = sweep.parse_openssl_time("notAfter=Jun 28 17:14:29 2026 GMT")

    assert parsed == datetime(2026, 6, 28, 17, 14, 29, tzinfo=timezone.utc)


def test_should_renew_at_or_below_threshold():
    assert sweep.should_renew(30, 30, force=False) is True
    assert sweep.should_renew(31, 30, force=False) is False
    assert sweep.should_renew(90, 30, force=True) is True


def test_build_registry_update_sql_skips_errors():
    ok = sweep.NodeResult(
        node="gateway",
        fqdn="jarvis-gateway.tail40ed36.ts.net",
        status="ok",
        days_remaining=45,
        cert_issued_at="2026-04-20T12:00:00+00:00",
        cert_expires_at="2026-07-19T12:00:00+00:00",
        source_cert="/Users/gate/jarvis/certs/gateway.crt",
    )
    bad = sweep.NodeResult(
        node="endpoint",
        fqdn="jarvis-endpoint.tail40ed36.ts.net",
        status="error",
        days_remaining=None,
        cert_issued_at=None,
        cert_expires_at=None,
        source_cert="remote",
        error="ssh failed",
    )

    sql = sweep.build_registry_update_sql([ok, bad])

    assert "WHERE name = 'gateway'" in sql
    assert "2026-07-19T12:00:00+00:00" in sql
    assert "endpoint" not in sql


def test_run_remote_node_changes_directory_before_python(monkeypatch):
    seen = {}

    def fake_run_command(args, **kwargs):
        seen["args"] = args

        class Result:
            returncode = 0
            stdout = (
                '{"node":"brain","fqdn":"jarvis-brain.tail40ed36.ts.net",'
                '"status":"ok","days_remaining":40,'
                '"cert_issued_at":"2026-04-01T00:00:00+00:00",'
                '"cert_expires_at":"2026-07-01T00:00:00+00:00",'
                '"source_cert":"/tmp/brain.crt"}'
            )
            stderr = ""

        return Result()

    monkeypatch.setattr(
        sweep,
        "load_node_map",
        lambda: {"brain": {"ssh_target": "jarvisbrain@example"}},
    )
    monkeypatch.setattr(sweep, "run_command", fake_run_command)

    result = sweep.run_remote_node(
        "brain",
        threshold_days=30,
        force=False,
        dry_run=True,
        no_restart=True,
    )

    assert result.status == "ok"
    assert seen["args"][-1].startswith("cd ~/jarvis-alpha && python3")
