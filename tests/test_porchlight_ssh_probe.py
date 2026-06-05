from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
PROBE_SCRIPT = REPO_ROOT / "scripts" / "porchlight_ssh_probe.sh"


def test_restore_drill_status_forced_command_reports_latest_drill(tmp_path):
    logs_dir = tmp_path / "jarvis" / "logs"
    logs_dir.mkdir(parents=True)
    report_path = logs_dir / "restore_drill_2026-06-05_172603.json"
    report_path.write_text(
        json.dumps(
            {
                "run_id": "2026-06-05_172603",
                "status": "pass",
                "source_dump": "jarvis_alpha.dump.gpg",
                "restore_rc": 1,
                "restore_err_count": 2,
                "pgaudit_err_count": 2,
                "table_count": 77,
                "ref_table_count": 77,
                "fail_reasons": "",
            }
        ),
        encoding="utf-8",
    )
    (logs_dir / "restore_drill.log").write_text(
        '{"event":"mm_notify_sent","run_id":"2026-06-05_172603","http_code":"200"}\n',
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(PROBE_SCRIPT)],
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HOME": str(tmp_path),
            "SSH_ORIGINAL_COMMAND": "porchlight restore-drill-status",
        },
        text=True,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["path"] == str(report_path)
    assert payload["run_id"] == "2026-06-05_172603"
    assert payload["status"] == "pass"
    assert payload["notification"] == {
        "event": "mm_notify_sent",
        "http_code": "200",
        "reason": "",
    }


def test_probe_rejects_unknown_forced_command(tmp_path):
    result = subprocess.run(
        [str(PROBE_SCRIPT)],
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HOME": str(tmp_path),
            "SSH_ORIGINAL_COMMAND": "python3 -c 'print(1)'",
        },
        text=True,
    )

    assert result.returncode == 126
    assert "Porchlight probe command denied" in result.stderr
