import json

import pytest
from pydantic import ValidationError

from brain.middleware.approval_classes import classify_route, determine_risk_tier
from brain.registry.catalog import INITIAL_AGENTS, INITIAL_SKILLS
from brain.registry.models import AgentSpec, SkillManifestV1, SkillSpec
from brain.routes.registry import _agent_from_row, _skill_from_row


def test_initial_skill_catalog_has_minimum_foundation_entries():
    names = {skill.name for skill in INITIAL_SKILLS}

    assert len(INITIAL_SKILLS) >= 10
    assert "notify.send" in names
    assert "notify.send_mattermost" in names
    assert "notify.send_pushover" in names
    assert "approval.canary_t4" in names
    assert "secrets.rotate" in names
    assert "chatops.command_read" in names
    assert "unifi.wan_status" in names
    assert "weather.current" in names
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
    assert skills["approval.canary_t4"].status == "active"
    assert skills["approval.canary_t4"].approval_tier == "T4"
    assert skills["approval.canary_t4"].metadata["approval_queue_bridge"] == "enabled"
    assert skills["approval.canary_t4"].metadata["canary"] is True
    assert skills["secrets.rotate"].status == "active"
    assert skills["secrets.rotate"].approval_tier == "T4"
    assert skills["secrets.rotate"].metadata["approval_required"] is True
    assert skills["weather.current"].status == "active"
    assert skills["weather.current"].approval_tier == "T1"
    assert (
        skills["weather.current"].metadata["manifest"]["egress"]["provider"]
        == "open_meteo"
    )


def test_initial_skill_catalog_has_complete_manifest_v1_contracts():
    for skill in INITIAL_SKILLS:
        manifest = SkillManifestV1.model_validate(skill.metadata["manifest"])

        assert manifest.manifest_version == 1
        assert manifest.input_schema_ref.startswith("registry://schemas/")
        assert manifest.output_schema_ref.startswith("registry://schemas/")
        assert manifest.runtime.timeout_s > 0
        assert manifest.audit.event_name == "skill.invoke"
        assert manifest.test_ref
        assert manifest.runbook_ref == "docs/JARVIS_Alpha_Skills_Agents_Catalog_v0_9.md"
        if skill.body_access:
            assert manifest.data_classification == "message_body"
        if skill.mutates_state:
            assert manifest.side_effect_class != "read"
        else:
            assert manifest.side_effect_class == "read"


def test_skill_requires_manifest_v1():
    with pytest.raises(ValidationError, match="manifest v1"):
        SkillSpec(
            name="notes.search",
            domain="notes",
            action="search",
            description="Search notes",
            approval_tier="T1",
            scope="notes.read",
            metadata={},
        )


def test_initial_agent_catalog_starts_agents_disabled_by_default_except_live_agents():
    agents = {agent.agent_id: agent for agent in INITIAL_AGENTS}

    assert agents["buddy"].enabled is True
    assert agents["dream_mode"].enabled is True
    assert agents["approval_triage"].enabled is True
    assert agents["watchdog"].enabled is True
    assert agents["porchlight"].enabled is True
    assert agents["keyturner"].enabled is True
    assert agents["warden"].enabled is True
    assert agents["ken_voice"].enabled is False
    assert agents["network_watchdog"].enabled is True
    assert agents["network_watchdog"].display_name == "Sweep"
    assert agents["approval_canary"].enabled is False
    assert agents["approval_canary"].risk_tier == "T4"
    assert "approval.canary_t4" in agents["approval_canary"].allowed_skills
    assert "notify.send" in agents["dream_mode"].allowed_skills
    assert "notify.send" in agents["approval_triage"].allowed_skills
    assert agents["porchlight"].launch_label == "com.jarvis.alpha.porchlight"
    assert agents["porchlight"].metadata["mattermost_channel_key"] == "security_alerts"
    assert agents["keyturner"].risk_tier == "T4"
    assert "secrets.rotate" in agents["keyturner"].allowed_skills
    assert agents["keyturner"].metadata["mattermost_channel_key"] == "security_alerts"
    assert agents["warden"].metadata["managed_agents"] == [
        "porchlight",
        "keyturner",
        "network_watchdog",
    ]
    assert agents["warden"].metadata["active_network_hardening"] == "unifi_cert_pinning"
    assert (
        agents["warden"].metadata["remediation_policy"]["T4_T5"]
        == "route_to_owner_with_approval"
    )
    assert (
        agents["network_watchdog"].metadata["active_hardening"] == "unifi_cert_pinning"
    )
    assert "unifi_tls_pin" in agents["network_watchdog"].metadata["monitors"]
    assert agents["approval_triage"].metadata["mattermost_channel_key"] == "needs_input"
    assert "weather.current" in agents["family_concierge"].allowed_skills
    assert "weather.read" in agents["family_concierge"].allowed_scopes


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


def test_skill_row_conversion_promotes_manifest_field():
    skill = next(item for item in INITIAL_SKILLS if item.name == "notify.send")
    row = {
        "skill_name": skill.name,
        "domain": skill.domain,
        "action": skill.action,
        "description": skill.description,
        "approval_tier": skill.approval_tier,
        "scope": skill.scope,
        "status": skill.status,
        "mutates_state": skill.mutates_state,
        "body_access": skill.body_access,
        "idempotency_required": skill.idempotency_required,
        "owner": skill.owner,
        "metadata": json.dumps(skill.metadata),
    }

    out = _skill_from_row(row)

    assert out.manifest is not None
    assert out.manifest.side_effect_class == "operator_notification"
    assert out.metadata["primary"] == "mattermost"


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


def test_keyturner_rotation_route_lets_skillrunner_own_approval():
    classes = classify_route("POST", "/v1/security/rotate-key")

    assert "keyturner_rotate" in classes
    assert "admin" not in classes
    assert determine_risk_tier(classes) == "T2"
