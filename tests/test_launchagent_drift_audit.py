from scripts.audit_launchagent_drift import (
    build_report,
    infer_node,
    parse_launchctl_output,
)


def test_parse_launchctl_output_extracts_alpha_labels():
    text = """PID\tStatus\tLabel
123\t0\tcom.jarvis.alpha.brain
-\t0\tcom.apple.some-service
456\t0\tcom.jarvis.alpha.buddy
"""

    assert parse_launchctl_output(text) == {
        "com.jarvis.alpha.brain",
        "com.jarvis.alpha.buddy",
    }


def test_build_report_separates_other_node_repo_labels():
    service_node_map = {
        "com.jarvis.alpha.brain": "brain",
        "com.jarvis.alpha.buddy": "brain",
        "com.jarvis.alpha.gateway": "gateway",
    }
    report = build_report(
        node="brain",
        repo_labels=set(service_node_map),
        loaded_labels={
            "com.jarvis.alpha.brain",
            "com.jarvis.alpha.gateway",
        },
        service_node_map=service_node_map,
    )

    assert report["status"] == "drift"
    assert report["missing_expected"] == ["com.jarvis.alpha.buddy"]
    assert report["other_node_repo_labels"] == ["com.jarvis.alpha.gateway"]
    assert report["other_node_loaded"] == ["com.jarvis.alpha.gateway"]


def test_infer_node_from_hostname():
    assert infer_node("jarvis-brain") == "brain"
    assert infer_node("jarvis-gateway") == "gateway"
