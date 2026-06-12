from datetime import datetime, timezone
import json

from scripts import sweep_tls_cert_renewal as sweep


def test_parse_openssl_time_reads_gmt_dates():
    parsed = sweep.parse_openssl_time("notAfter=Jun 28 17:14:29 2026 GMT")

    assert parsed == datetime(2026, 6, 28, 17, 14, 29, tzinfo=timezone.utc)


def test_should_renew_at_or_below_threshold():
    assert sweep.should_renew(30, 30, force=False) is True
    assert sweep.should_renew(31, 30, force=False) is False
    assert sweep.should_renew(90, 30, force=True) is True


def test_min_validity_duration_uses_threshold_hours():
    assert sweep.min_validity_duration(30) == "720h"
    assert sweep.min_validity_duration(0) == "24h"


def test_cert_moved_forward_requires_later_expiry():
    previous = datetime(2026, 6, 28, 17, 14, 29, tzinfo=timezone.utc)
    same = datetime(2026, 6, 28, 17, 14, 29, tzinfo=timezone.utc)
    later = datetime(2026, 8, 30, 17, 14, 29, tzinfo=timezone.utc)

    assert sweep.cert_moved_forward(previous, same) is False
    assert sweep.cert_moved_forward(previous, later) is True


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


def test_check_health_uses_primary_url_when_healthy(monkeypatch):
    seen = []

    def fake_run_command(args, **kwargs):
        seen.append(args[-1])

        class Result:
            returncode = 0
            stdout = "200"
            stderr = ""

        return Result()

    monkeypatch.setattr(sweep, "run_command", fake_run_command)

    assert (
        sweep.check_health(
            "https://jarvis-sandbox.tail40ed36.ts.net:5001/api/health",
            ("https://127.0.0.1:5001/api/health",),
        )
        is True
    )
    assert seen == ["https://jarvis-sandbox.tail40ed36.ts.net:5001/api/health"]


def test_check_health_falls_back_after_primary_resolution_failure(monkeypatch):
    seen = []

    def fake_run_command(args, **kwargs):
        seen.append(args[-1])

        class Result:
            stderr = ""
            if args[-1] == "https://127.0.0.1:5001/api/health":
                returncode = 0
                stdout = "200"
            else:
                returncode = 6
                stdout = "000"

        return Result()

    monkeypatch.setattr(sweep, "run_command", fake_run_command)

    assert (
        sweep.check_health(
            "https://jarvis-sandbox.tail40ed36.ts.net:5001/api/health",
            ("https://127.0.0.1:5001/api/health",),
        )
        is True
    )
    assert seen == [
        "https://jarvis-sandbox.tail40ed36.ts.net:5001/api/health",
        "https://127.0.0.1:5001/api/health",
    ]


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


def test_run_node_uses_local_path_for_current_node(monkeypatch):
    called = []

    def fake_local(spec, **kwargs):
        called.append(("local", spec.node, kwargs))
        return sweep.NodeResult(
            node=spec.node,
            fqdn=spec.fqdn,
            status="ok",
            days_remaining=42,
            cert_issued_at="2026-04-01T00:00:00+00:00",
            cert_expires_at="2026-07-01T00:00:00+00:00",
            source_cert="/tmp/brain.crt",
        )

    def fake_remote(node, **kwargs):
        called.append(("remote", node, kwargs))
        return sweep.NodeResult(
            node=node,
            fqdn=sweep.NODE_SPECS[node].fqdn,
            status="ok",
            days_remaining=42,
            cert_issued_at="2026-04-01T00:00:00+00:00",
            cert_expires_at="2026-07-01T00:00:00+00:00",
            source_cert="remote",
        )

    monkeypatch.setattr(sweep, "renew_local_node", fake_local)
    monkeypatch.setattr(sweep, "run_remote_node", fake_remote)

    result = sweep.run_node(
        "brain",
        threshold_days=30,
        force=False,
        dry_run=True,
        no_restart=True,
        current_node="brain",
    )

    assert result.status == "ok"
    assert called == [
        (
            "local",
            "brain",
            {
                "threshold_days": 30,
                "force": False,
                "dry_run": True,
                "no_restart": True,
            },
        )
    ]


def test_sweep_report_signature_is_stable():
    result = sweep.NodeResult(
        node="brain",
        fqdn="jarvis-brain.tail40ed36.ts.net",
        status="ok",
        days_remaining=85,
        cert_issued_at="2026-06-01T00:00:00+00:00",
        cert_expires_at="2026-09-01T00:00:00+00:00",
        source_cert="/Users/jarvisbrain/jarvis/certs/brain.crt",
        health_ok=True,
    )
    body = sweep.sweep_report_body(
        result,
        threshold_days=30,
        reported_at=datetime(2026, 6, 12, 12, 0, 0, tzinfo=timezone.utc),
    )

    signature = sweep.sign_report_body("secret", timestamp="1791806400", body=body)

    assert json.loads(body)["node"] == "brain"
    assert (
        signature == "1a7453819ebf90b4854fad4753ff7ca7bacaed78393265e91837a3d866d3a651"
    )


def test_post_sweep_report_uses_signed_headers(monkeypatch):
    result = sweep.NodeResult(
        node="sandbox",
        fqdn="jarvis-sandbox.tail40ed36.ts.net",
        status="ok",
        days_remaining=44,
        cert_issued_at="2026-06-01T00:00:00+00:00",
        cert_expires_at="2026-07-27T00:00:00+00:00",
        source_cert="/Users/jarvissand/jarvis/certs/sandbox.crt",
        health_ok=True,
    )
    captured = {}

    class FakeResponse:
        status = 202

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["headers"] = dict(request.header_items())
        captured["body"] = request.data
        return FakeResponse()

    monkeypatch.setattr(sweep, "urlopen", fake_urlopen)
    monkeypatch.setattr(sweep.time, "time", lambda: 1791806400)

    posted = sweep.post_sweep_report(
        result,
        threshold_days=30,
        report_url="https://brain.example/v1/security/sweep-report",
        secret="secret",
    )

    assert posted == {"posted": True, "status": 202}
    assert captured["url"] == "https://brain.example/v1/security/sweep-report"
    assert captured["headers"]["X-jarvis-node"] == "sandbox"
    assert captured["headers"]["X-jarvis-timestamp"] == "1791806400"
    assert "X-jarvis-signature" in captured["headers"]
    assert json.loads(captured["body"])["threshold_days"] == 30


def test_post_sweep_report_is_nonblocking_without_secret():
    result = sweep.NodeResult(
        node="endpoint",
        fqdn="jarvis-endpoint.tail40ed36.ts.net",
        status="ok",
        days_remaining=85,
        cert_issued_at="2026-06-01T00:00:00+00:00",
        cert_expires_at="2026-09-01T00:00:00+00:00",
        source_cert="/Users/jarvisendpoint/jarvis/certs/endpoint.crt",
    )

    posted = sweep.post_sweep_report(
        result,
        threshold_days=30,
        report_url="https://brain.example/v1/security/sweep-report",
        secret=None,
    )

    assert posted == {"posted": False, "reason": "missing_report_secret"}
