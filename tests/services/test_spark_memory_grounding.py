from __future__ import annotations

from pathlib import Path

from brain.services.spark_memory_grounding import (
    collect_spark_memory_grounding_status,
    load_spark_memory_grounding,
)
from brain.services.spark_voice_feedback import FEEDBACK_FILENAME


def test_spark_memory_grounding_loads_bounded_reviewed_context(
    tmp_path: Path,
) -> None:
    vault_root = _write_personality_vault(tmp_path)
    feedback_root = _write_feedback_root(tmp_path)

    grounding = load_spark_memory_grounding(
        principal_id="ken",
        vault_root=vault_root,
        feedback_root=feedback_root,
    )

    assert grounding is not None
    block = grounding.to_context_block()
    assert block.startswith("[WHO YOU'RE TALKING TO]\n- Principal: ken.")
    assert "Voice target: optimistic, cheerful, playful" in block
    assert "Avoid sounding: robotic, rambling, salesy" in block
    assert "Use signature phrases sparingly: cheers, fair enough" in block
    assert "Text: Less formal, short, direct." in block
    assert "Uncertainty: Admit uncertainty and do not fake confidence." in block
    assert "Boundary: Legal and medical topics stay draft-only." in block
    assert "Draft edit feedback waiting for review: 2." in block

    lowered = block.lower()
    assert "raw thread" not in lowered
    assert "phone number" not in lowered
    assert len(grounding.lines) <= 18


def test_spark_memory_grounding_skips_unsafe_or_anonymous_principal(
    tmp_path: Path,
) -> None:
    vault_root = _write_personality_vault(tmp_path)

    assert (
        load_spark_memory_grounding(
            principal_id="anon",
            vault_root=vault_root,
            feedback_root=tmp_path,
        )
        is None
    )
    assert (
        load_spark_memory_grounding(
            principal_id="../ken",
            vault_root=vault_root,
            feedback_root=tmp_path,
        )
        is None
    )


def test_spark_memory_grounding_status_is_buddy_safe(tmp_path: Path) -> None:
    status = collect_spark_memory_grounding_status(
        principal_id="ken",
        vault_root=tmp_path / "missing-vault",
        feedback_root=tmp_path / "missing-feedback",
    )

    assert status["principal_id"] == "ken"
    assert status["status"] == "unavailable"
    assert status["line_count"] == 0
    assert status["feedback_count"] == 0
    assert "error_class" in status


def _write_personality_vault(tmp_path: Path) -> Path:
    principal_root = tmp_path / "personality" / "spark" / "principals" / "ken"
    principal_root.mkdir(parents=True)
    (principal_root / "voice.md").write_text(
        """
# Ken Voice

Ken-approved voice markers:
- optimistic
- cheerful
- playful

Ken-approved recurring phrases:
- cheers
- fair enough

Avoid sounding:
- robotic
- rambling
- salesy

## Channel Style

| Channel | Rule |
|---|---|
| Text | Less formal, short, direct. |
| Email | More formal, still clear. |
| AI chat | Between text and email. |

## Accessibility Style

Prefer:
- bullets
- visual structure
- short sections

## Judgment Style

| Situation | Rule |
|---|---|
| Uncertainty | Admit uncertainty and do not fake confidence. |
| Disagreement | Kindly but directly. |
| Saying no | Clear boundary, no condescension. |
| Urgency | Acknowledge, give timeline, move. |
""",
        encoding="utf-8",
    )
    (principal_root / "boundaries.md").write_text(
        """
# Spark Boundaries

## Hard Boundaries
- Legal and medical topics stay draft-only.
- Never expose raw thread or phone number details.

## Extra Caution Topics
- Relationship topics require explicit review.

## Default On Ambiguity
- Ask before sending or storing new memory.
""",
        encoding="utf-8",
    )
    return tmp_path / "personality"


def _write_feedback_root(tmp_path: Path) -> Path:
    feedback_dir = tmp_path / "feedback" / "spark" / "principals" / "ken" / "feedback"
    feedback_dir.mkdir(parents=True)
    (feedback_dir / FEEDBACK_FILENAME).write_text(
        '{"candidate_key_phrases":["fair enough"]}\n'
        '{"candidate_key_phrases":["cheers"]}\n',
        encoding="utf-8",
    )
    return tmp_path / "feedback"
