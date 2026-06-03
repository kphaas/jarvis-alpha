import json

from brain.agents.porchlight import _parse_porchlight_json


def test_parse_porchlight_json_accepts_clean_report():
    report = {"agent": "Porchlight", "status": "pass"}

    assert _parse_porchlight_json(json.dumps(report)) == report


def test_parse_porchlight_json_ignores_stdout_noise():
    report = {"agent": "Porchlight", "status": "fail", "counts": {"failing": 1}}
    noisy = "secret_access key=GATEWAY_TOKEN source=file\n" + json.dumps(
        report, indent=2
    )

    assert _parse_porchlight_json(noisy) == report
