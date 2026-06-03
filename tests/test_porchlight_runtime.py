import json

from brain.agents.porchlight import _parse_porchlight_json


def test_parse_porchlight_json_accepts_clean_report():
    report = {"agent": "Porchlight", "status": "pass", "counts": {}, "checks": []}

    assert _parse_porchlight_json(json.dumps(report)) == report


def test_parse_porchlight_json_ignores_stdout_noise():
    report = {
        "agent": "Porchlight",
        "status": "fail",
        "counts": {"failing": 1},
        "checks": [],
    }
    noisy = "secret_access key=GATEWAY_TOKEN source=file\n" + json.dumps(
        report, indent=2
    )

    assert _parse_porchlight_json(noisy) == report


def test_parse_porchlight_json_ignores_json_log_lines():
    log = {
        "ts": "2026-06-03T20:17:35Z",
        "level": "INFO",
        "message": "secret_access key=GITHUB_TOKEN source=env",
    }
    report = {
        "agent": "Porchlight",
        "status": "fail",
        "counts": {"failing": 1},
        "checks": [{"name": "postgres_role_safety"}],
    }
    noisy = "\n".join([json.dumps(log), json.dumps(log), json.dumps(report, indent=2)])

    assert _parse_porchlight_json(noisy) == report
