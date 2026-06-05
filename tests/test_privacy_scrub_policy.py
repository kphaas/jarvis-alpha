from __future__ import annotations

from uuid import uuid4

import pytest

from brain.agents.privacy_scrub.policy import ActionType, evaluate_tier
from brain.agents.privacy_scrub.subjects import Role, Subject
from brain.agents.privacy_scrub.targets import (
    Jurisdiction,
    OptOutMethod,
    Target,
    TargetCategory,
)


def _ken() -> Subject:
    return Subject(
        id=uuid4(),
        user_id="ken",
        display_name="Ken",
        role=Role.ADULT,
    )


def _ryleigh() -> Subject:
    return Subject(
        id=uuid4(),
        user_id="ken",
        display_name="Ryleigh",
        role=Role.MINOR,
        guardian_user_id="ken",
    )


def _broker(**overrides) -> Target:
    values = {
        "id": "spokeo_test",
        "name": "Spokeo (test)",
        "category": TargetCategory.DATA_BROKER,
        "jurisdiction": Jurisdiction.US_FEDERAL,
        "opt_out_method": OptOutMethod.WEB_FORM,
        "supports_minors": False,
    }
    values.update(overrides)
    return Target(**values)


def _court() -> Target:
    return Target(
        id="ga_fulton_superior",
        name="Fulton Superior Court",
        category=TargetCategory.PUBLIC_RECORD,
        jurisdiction=Jurisdiction.US_GA,
        opt_out_method=OptOutMethod.COURT_MOTION,
        supports_minors=False,
    )


def test_local_scan_is_t1():
    assert evaluate_tier(_ken(), ActionType.SCAN_LOCAL, _broker()).tier == "T1"
    assert evaluate_tier(_ryleigh(), ActionType.SCAN_LOCAL, _broker()).tier == "T1"


def test_external_scan_requires_approval_for_adult():
    decision = evaluate_tier(_ken(), ActionType.SCAN_EXTERNAL, _broker())

    assert decision.tier == "T4"
    assert "third party" in decision.reason.lower()


def test_external_scan_for_minor_is_t5_manual():
    decision = evaluate_tier(_ryleigh(), ActionType.SCAN_EXTERNAL, _broker())

    assert decision.tier == "T5"
    assert decision.method_override == OptOutMethod.MANUAL_ONLY


def test_minor_send_opt_out_is_always_t5_even_if_supported():
    decision = evaluate_tier(
        _ryleigh(),
        ActionType.SEND_OPT_OUT,
        _broker(supports_minors=True),
    )

    assert decision.tier == "T5"
    assert decision.method_override == OptOutMethod.MANUAL_ONLY


def test_adult_send_opt_out_is_t4_not_notify_only():
    decision = evaluate_tier(_ken(), ActionType.SEND_OPT_OUT, _broker())

    assert decision.tier == "T4"
    assert decision.method_override is None


def test_sensitive_adult_send_escalates_to_t5():
    decision = evaluate_tier(
        _ken(),
        ActionType.SEND_OPT_OUT,
        _broker(requires_identity_document=True),
    )

    assert decision.tier == "T5"
    assert decision.method_override == OptOutMethod.MANUAL_ONLY


def test_court_motion_file_is_t5_for_everyone():
    assert evaluate_tier(_ken(), ActionType.FILE_MOTION, _court()).tier == "T5"
    assert evaluate_tier(_ryleigh(), ActionType.FILE_MOTION, _court()).tier == "T5"


def test_court_motion_draft_is_t4():
    decision = evaluate_tier(_ken(), ActionType.DRAFT, _court())

    assert decision.tier == "T4"


def test_non_court_draft_is_t2():
    assert evaluate_tier(_ken(), ActionType.DRAFT, _broker()).tier == "T2"


def test_minor_non_court_draft_is_t4():
    decision = evaluate_tier(_ryleigh(), ActionType.DRAFT, _broker())

    assert decision.tier == "T4"
    assert "adult review" in decision.reason.lower()


def test_verify_for_adult_is_t4():
    assert evaluate_tier(_ken(), ActionType.VERIFY, _broker()).tier == "T4"


def test_verify_for_minor_is_t5():
    decision = evaluate_tier(_ryleigh(), ActionType.VERIFY, _broker())

    assert decision.tier == "T5"
    assert decision.method_override == OptOutMethod.MANUAL_ONLY


@pytest.mark.parametrize(
    "action",
    [ActionType.SEND_OPT_OUT, ActionType.SCAN_EXTERNAL, ActionType.VERIFY],
)
@pytest.mark.parametrize("supports_minors", [True, False])
def test_minor_external_actions_never_drop_below_t5(action, supports_minors):
    decision = evaluate_tier(
        _ryleigh(),
        action,
        _broker(supports_minors=supports_minors),
    )

    assert decision.tier == "T5"
