from __future__ import annotations

import pytest

from brain.services.herald_press_outreach import (
    MAX_WEEKLY_PRESS_DRAFTS,
    PressTarget,
    clean_proof_points,
    create_press_pitch_draft,
    create_weekly_press_pitch_batch,
    hash_press_pitch,
    select_weekly_press_batch,
)


PROOF_POINTS = (
    "Public press kit and approved positioning are live at at-0.com/press.",
    "Sanitized capability cards show Alpha, Helm, Family, Finance, Forge, and Print boundaries.",
    "High-stakes workflows remain human-approved and draft-first.",
)


def _target(index: int) -> PressTarget:
    return PressTarget(
        name=f"Reporter {index}",
        outlet=f"Outlet {index}",
        beat="AI infrastructure, privacy, and operator-controlled products",
        public_profile_url=f"https://example.com/reporter-{index}",
        angle="private AI with evidence-backed human approval instead of broad launch claims",
    )


def test_press_pitch_is_draft_only_and_fact_bounded() -> None:
    draft = create_press_pitch_draft(
        target=PressTarget(
            name="Hayden Field",
            outlet="The Verge",
            beat="AI companies, societal impact, and technology policy",
            public_profile_url="https://www.theverge.com/authors/hayden-field",
            angle="private AI proof with high-stakes approval boundaries",
        ),
        proof_points=PROOF_POINTS,
    )

    assert "AT0" in draft.subject
    assert "AT-0" not in draft.subject
    assert "AT-0" not in draft.body_text
    assert "trillion" not in draft.body_text.lower()
    assert "public availability" in draft.body_text
    assert "draft_only_no_send" in draft.safety_flags
    assert "human_review_required" in draft.safety_flags
    assert "fact_check_required" in draft.safety_flags
    assert "source_revalidation_required" in draft.safety_flags
    assert "brand_name_violation" not in draft.safety_flags
    assert draft.content_hash == hash_press_pitch(
        subject=draft.subject,
        body_text=draft.body_text,
    )


def test_weekly_press_batch_caps_at_five_and_deduplicates() -> None:
    targets = [_target(index) for index in range(1, 7)]
    targets.insert(2, _target(2))

    selected = select_weekly_press_batch(targets)
    batch = create_weekly_press_pitch_batch(
        targets=targets,
        proof_points=PROOF_POINTS,
    )

    assert len(selected) == MAX_WEEKLY_PRESS_DRAFTS
    assert len(batch) == MAX_WEEKLY_PRESS_DRAFTS
    assert selected[0].name == "Reporter 1"
    assert selected[1].name == "Reporter 2"
    assert all("draft_only_no_send" in draft.safety_flags for draft in batch)


def test_weekly_press_batch_rejects_unsafe_limit() -> None:
    with pytest.raises(ValueError, match="weekly_press_limit_exceeded"):
        select_weekly_press_batch(
            [_target(index) for index in range(1, 8)],
            limit=MAX_WEEKLY_PRESS_DRAFTS + 1,
        )


def test_press_pitch_rejects_weak_sources_and_claims() -> None:
    with pytest.raises(ValueError, match="public_source_url_must_be_https"):
        create_press_pitch_draft(
            target=PressTarget(
                name="Reporter",
                outlet="Outlet",
                beat="AI infrastructure and privacy",
                public_profile_url="http://example.com/reporter",
                angle="private AI with proof-first outreach",
            ),
            proof_points=PROOF_POINTS,
        )

    assert clean_proof_points(
        [
            "Public press kit and approved positioning are live at at-0.com/press.",
            "Public press kit and approved positioning are live at at-0.com/press.",
            "High-stakes workflows remain human-approved and draft-first.",
        ]
    ) == (
        "Public press kit and approved positioning are live at at-0.com/press.",
        "High-stakes workflows remain human-approved and draft-first.",
    )
