from brain.registry.catalog import INITIAL_SKILLS
from brain.registry.drift import (
    assert_skill_handler_coverage,
    evaluate_skill_handler_coverage,
)
from brain.skills.handlers import all_skill_handlers


def test_active_skillrunner_skills_have_handlers_and_no_orphans():
    assert_skill_handler_coverage(INITIAL_SKILLS, all_skill_handlers())


def test_guard_includes_obsidian_skills_declared_for_dream_mode():
    handlers = all_skill_handlers()

    assert "notes.search" in handlers
    assert "tasks.create" in handlers
    assert "weather.current" in handlers
    assert "approval.canary_t4" in handlers
    assert "secrets.rotate" in handlers


def test_guard_reports_missing_active_handler():
    skill = next(item for item in INITIAL_SKILLS if item.name == "notes.search")
    handlers = all_skill_handlers()
    handlers.pop("notes.search")

    report = evaluate_skill_handler_coverage([skill], handlers)

    assert report.missing_active_handlers == ["notes.search"]


def test_guard_reports_active_high_risk_skill_without_approval_bridge():
    skill = next(item for item in INITIAL_SKILLS if item.name == "gmail.send")
    active_skill = skill.model_copy(update={"status": "active"})

    report = evaluate_skill_handler_coverage(
        [active_skill],
        {"gmail.send": lambda call: {"ok": True}},
    )

    assert report.active_high_risk_without_bridge == ["gmail.send"]


def test_route_owned_active_skills_must_opt_out_explicitly():
    skill = next(item for item in INITIAL_SKILLS if item.name == "chatops.command_read")

    report = evaluate_skill_handler_coverage([skill], {})

    assert report.ok
