from brain.routes.security import (
    PORCHLIGHT_COMPLETENESS_CHECK,
    PORCHLIGHT_REQUIRED_CHECKS,
    _guard_porchlight_report_completeness,
)


def _check(name: str, status: str = "pass") -> dict:
    return {
        "name": name,
        "status": status,
        "severity": "info",
        "summary": f"{name} summary",
    }


def test_porchlight_report_completeness_guard_keeps_full_report_unchanged():
    report = {
        "agent": "Porchlight",
        "status": "pass",
        "severity": "info",
        "counts": {
            "checks": len(PORCHLIGHT_REQUIRED_CHECKS),
            "passing": len(PORCHLIGHT_REQUIRED_CHECKS),
            "warning": 0,
            "failing": 0,
        },
        "checks": [_check(name) for name in PORCHLIGHT_REQUIRED_CHECKS],
    }

    assert _guard_porchlight_report_completeness(report) is report


def test_porchlight_report_completeness_guard_flags_partial_report():
    report = {
        "agent": "Porchlight",
        "status": "warn",
        "severity": "medium",
        "counts": {"checks": 1, "passing": 0, "warning": 1, "failing": 0},
        "checks": [
            {
                "name": "postgres_role_safety",
                "status": "warn",
                "severity": "medium",
                "summary": "Postgres bootstrap superuser risk is accepted.",
            }
        ],
    }

    guarded = _guard_porchlight_report_completeness(report)

    assert guarded is not report
    assert guarded["status"] == "fail"
    assert guarded["severity"] == "high"
    assert guarded["counts"] == {
        "checks": 2,
        "passing": 0,
        "warning": 1,
        "failing": 1,
    }
    assert guarded["checks"][0]["name"] == PORCHLIGHT_COMPLETENESS_CHECK
    assert "code_malware_scan" in guarded["checks"][0]["detail"]
    assert "runtime_exposure" in guarded["checks"][0]["metadata"]["missing_checks"]
