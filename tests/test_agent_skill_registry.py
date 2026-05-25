import json

import pytest
from pydantic import ValidationError

from brain.middleware.approval_classes import classify_route, determine_risk_tier
from brain.registry.catalog import INITIAL_AGENTS, INITIAL_SKILLS
from brain.registry.models import AgentSpec, SkillSpec
from brain.routes.registry import _agent_from_row, _skill_from_row


def test_initial_skill_catalog_has_minimum_foundation_entries():
    names = {skill.name for skill in INITIAL_SKILLS}

    assert len(INITIAL_SKILLS) >= 10
    assert "notify.send" in names
    assert "notify.send_mattermost" in names
    assert "notify.send_pushover" in names
    assert "unifi.wan_status" in names
    assert "gmail.send" in names
    assert "gmail.send_vip" in names
    assert "imessage.send" in names
    assert "imessage.send_vip" in names
    assert "smarthome.run_trusted_scene" in names
    assert "smarthome.unlock" in names
    assert "smarthome.alarm_disarm" in names
    skills = {skill.name: skill for skill in INITIAL_SKILLS}
    assert skills["notify.send"].status == "active"
    assert skills["notify.send"].metadata["primary"] == "mattermost"
    assert skills["notify.send"].metadata["delivery"] == "incoming_webhook"
    assert skills["notify.send_mattermost"].status == "active"
    assert skills["notify.send_mattermost"].metadata["delivery"] == "incoming_webhook"
    assert skills["notify.send_pushover"].status == "active"


def test_initial_agent_catalog_starts_agents_disabled_by_default_except_live_agents():
    agents = {agent.agent_id: agent for agent in INITIAL_AGENTS}

    assert agents["buddy"].enabled is True
    assert agents["dream_mode"].enabled is True
    assert agents["ken_voice"].enabled is False
    assert agents["network_watchdog"].enabled is False


def test_skill_name_requires_dot_separated_snake_case():
    with pytest.raises(ValidationError):
        SkillSpec(
            name="SmartHome.SetDevice",
            domain="smarthome",
            action="set_device",
            description="bad name",
            approval_tier="T4",
            scope="smarthome.write",
        )


def test_skill_name_must_match_domain_and_action():
    with pytest.raises(ValidationError):
        SkillSpec(
            name="gmail.send",
            domain="gmail",
            action="draft_reply",
            description="mismatched contract",
            approval_tier="T2",
            scope="email.write",
        )


def test_agent_id_requires_snake_case():
    with pytest.raises(ValidationError):
        AgentSpec(
            agent_id="NetworkWatchdog",
            display_name="Network Watchdog",
            purpose="bad id",
            risk_tier="T1",
        )


def test_agent_cost_cap_cannot_be_negative():
    with pytest.raises(ValidationError):
        AgentSpec(
            agent_id="network_watchdog",
            display_name="Network Watchdog",
            purpose="bad cap",
            risk_tier="T1",
            cost_daily_cap_usd=-0.01,
        )


def test_skill_row_conversion_accepts_jsonb_string():
    row = {
        "skill_name": "gmail.send",
        "domain": "gmail",
        "action": "send",
        "description": "Send mail",
        "approval_tier": "T4",
        "scope": "email.send",
        "status": "planned",
        "mutates_state": True,
        "body_access": True,
        "idempotency_required": True,
        "owner": "ken",
        "metadata": json.dumps({"vip_policy": "non_vip_t4"}),
    }

    out = _skill_from_row(row)

    assert out.name == "gmail.send"
    assert out.metadata == {"vip_policy": "non_vip_t4"}


def test_agent_row_conversion_casts_arrays_and_cost_cap():
    row = {
        "agent_id": "network_watchdog",
        "display_name": "Network Watchdog",
        "purpose": "Monitor network",
        "risk_tier": "T1",
        "status": "planned",
        "enabled": False,
        "owner": "ken",
        "cadence": "30s",
        "launch_label": None,
        "allowed_skills": ("unifi.wan_status", "unifi.clients"),
        "allowed_scopes": ("network.read",),
        "cost_daily_cap_usd": "0.0000",
        "model_policy": "{}",
        "approval_policy": "{}",
        "metadata": "{}",
    }

    out = _agent_from_row(row)

    assert out.agent_id == "network_watchdog"
    assert out.allowed_skills == ["unifi.wan_status", "unifi.clients"]
    assert out.cost_daily_cap_usd == 0.0


def test_agent_enable_disable_routes_are_t5_admin_control_plane():
    enable_classes = classify_route("POST", "/v1/agents/network_watchdog/enable")
    disable_classes = classify_route("POST", "/v1/agents/network_watchdog/disable")

    assert determine_risk_tier(enable_classes) == "T5"
    assert determine_risk_tier(disable_classes) == "T5"
