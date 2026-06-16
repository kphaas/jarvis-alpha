from __future__ import annotations

import json

from pydantic import ValidationError

from brain.services.spark_persona_guardrails import (
    SparkGuardrailState,
    default_spark_guardrails,
    is_core_family_target_label,
    load_spark_guardrails,
    save_spark_guardrails,
)


def test_default_spark_guardrails_start_draft_only_and_no_auto_send() -> None:
    state = default_spark_guardrails()

    assert state.principal_id == "ken"
    assert state.active_mode == "draft_only"
    assert state.auto_send_enabled is False
    assert "legal" in state.protected_topics
    assert "medical" in state.protected_topics
    assert "minor" in state.protected_topics
    assert [item.id for item in state.protected_relationships] == [
        "ken",
        "sweta",
        "ryleigh",
        "sloane",
    ]
    assert "robotic" in state.calibration.avoid_voice
    assert "fair enough" in state.calibration.signature_phrases


def test_spark_guardrails_reject_auto_send_enabled() -> None:
    payload = default_spark_guardrails().model_dump(mode="json")
    payload["auto_send_enabled"] = True

    try:
        SparkGuardrailState.model_validate(payload)
    except ValidationError as exc:
        assert "auto_send_enabled is not available" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("auto_send_enabled should be blocked in this phase")


def test_spark_guardrails_save_and_load_round_trip(tmp_path) -> None:
    path = tmp_path / "guardrails.json"
    state = default_spark_guardrails().model_copy(
        update={"active_mode": "hybrid_review"}
    )

    saved = save_spark_guardrails(state, path=path)
    loaded = load_spark_guardrails(path=path)

    assert path.exists()
    assert saved.active_mode == "hybrid_review"
    assert loaded.active_mode == "hybrid_review"
    assert loaded.auto_send_enabled is False
    assert loaded.updated_at == saved.updated_at


def test_spark_guardrails_strip_non_core_relationships_on_load(tmp_path) -> None:
    path = tmp_path / "guardrails.json"
    payload = default_spark_guardrails().model_dump(mode="json")
    payload["protected_relationships"].append(
        {
            "id": "mother",
            "label": "Mother",
            "relationship": "parent",
            "sensitivity": "family",
            "default_mode": "draft_only",
            "approval_required": True,
            "notes": None,
        }
    )
    path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = load_spark_guardrails(path=path)

    assert [item.id for item in loaded.protected_relationships] == [
        "ken",
        "sweta",
        "ryleigh",
        "sloane",
    ]


def test_spark_guardrails_load_missing_path_returns_default(tmp_path) -> None:
    state = load_spark_guardrails(path=tmp_path / "missing.json")

    assert state.principal_id == "ken"
    assert state.auto_send_enabled is False


def test_core_family_target_labels_include_ken_and_exclude_non_family() -> None:
    assert is_core_family_target_label("Ken") is True
    assert is_core_family_target_label("Mother") is False
