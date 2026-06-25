import json

import pytest
from pydantic import ValidationError

from brain.middleware.approval_classes import classify_route, determine_risk_tier
from brain.registry.catalog import INITIAL_AGENTS, INITIAL_SKILLS
from brain.registry.data_sources import (
    DEFAULT_DATA_SOURCE_REGISTRY_ROOT,
    assert_skill_data_source_coverage,
    load_data_source_registry,
)
from brain.registry.models import AgentSpec, SkillManifestV1, SkillSpec
from brain.routes.registry import _agent_from_row, _skill_from_row


def test_initial_skill_catalog_has_minimum_foundation_entries():
    names = {skill.name for skill in INITIAL_SKILLS}

    assert len(INITIAL_SKILLS) >= 10
    assert "notify.send" in names
    assert "notify.send_mattermost" in names
    assert "notify.send_pushover" in names
    assert "agent_board.read" in names
    assert "agent_board.queue_item" in names
    assert "agent_board.update_status" in names
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
    assert "internet_scout.search" in names
    assert "internet_scout.deep_research" in names
    assert "internet_scout.browser_task" in names
    assert "notes.write_private_digest" in names
    skills = {skill.name: skill for skill in INITIAL_SKILLS}
    assert skills["notify.send"].status == "active"
    assert skills["notify.send"].metadata["primary"] == "mattermost"
    assert skills["notify.send"].metadata["delivery"] == "incoming_webhook"
    assert skills["notify.send_mattermost"].status == "active"
    assert skills["notify.send_mattermost"].metadata["delivery"] == "incoming_webhook"
    assert skills["notify.send_pushover"].status == "active"
    assert skills["agent_board.read"].approval_tier == "T1"
    assert skills["agent_board.queue_item"].approval_tier == "T2"
    assert skills["agent_board.queue_item"].mutates_state is True
    assert skills["agent_board.queue_item"].metadata["does_not_execute_agents"] is True
    assert skills["agent_board.update_status"].metadata["operator_surface"] == "helm"
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
    assert (
        skills["weather.current"].metadata["manifest"]["egress"]["data_source_id"]
        == "open-meteo"
    )
    assert skills["internet_scout.search"].status == "active"
    assert skills["internet_scout.search"].body_access is True
    assert skills["internet_scout.search"].approval_tier == "T2"
    assert skills["internet_scout.deep_research"].approval_tier == "T3"
    assert skills["internet_scout.browser_task"].approval_tier == "T4"
    assert skills["internet_scout.browser_task"].mutates_state is True
    assert sorted(
        skills["internet_scout.search"].metadata["manifest"]["egress"][
            "data_source_ids"
        ]
    ) == ["brave-search", "perplexity-search"]
    assert sorted(
        skills["internet_scout.deep_research"].metadata["manifest"]["egress"][
            "data_source_ids"
        ]
    ) == ["brave-search", "perplexity-search"]
    assert skills["internet_scout.search"].metadata["execution_path"] == (
        "fastapi_route"
    )
    assert skills["internet_scout.deep_research"].metadata["execution_path"] == (
        "fastapi_route"
    )
    assert skills["internet_scout.browser_task"].metadata["execution_path"] == (
        "fastapi_route"
    )
    assert (
        skills["internet_scout.browser_task"].metadata["manifest"]["egress"]["provider"]
        == "beacon_browser_runtime"
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
        assert manifest.runbook_ref in {
            "docs/JARVIS_Alpha_Skills_Agents_Catalog_v0_9.md",
            "docs/adr/ADR-0019-beacon-internet-scout.md",
        }
        if skill.body_access:
            assert manifest.data_classification == "message_body"
        if skill.mutates_state:
            assert manifest.side_effect_class != "read"
        else:
            assert manifest.side_effect_class == "read"


def test_active_external_data_skills_reference_vendored_data_sources():
    assert DEFAULT_DATA_SOURCE_REGISTRY_ROOT.exists()

    data_sources = load_data_source_registry(DEFAULT_DATA_SOURCE_REGISTRY_ROOT)
    assert data_sources["open-meteo"].domain == "weather"
    assert data_sources["brave-search"].domain == "web-search"
    assert data_sources["perplexity-search"].domain == "web-search"

    assert_skill_data_source_coverage(INITIAL_SKILLS, data_sources)


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
    skills = {skill.name: skill for skill in INITIAL_SKILLS}

    assert agents["buddy"].enabled is True
    assert agents["dream_mode"].enabled is True
    assert agents["approval_triage"].enabled is True
    assert agents["watchdog"].enabled is True
    assert agents["porchlight"].enabled is True
    assert agents["keyturner"].enabled is True
    assert agents["warden"].enabled is True
    assert agents["ken_voice"].enabled is False
    assert agents["sweep"].enabled is True
    assert agents["sweep"].display_name == "Sweep"
    assert agents["tripwire"].enabled is True
    assert agents["tripwire"].display_name == "Tripwire"
    assert agents["ledger"].enabled is True
    assert agents["ledger"].display_name == "Ledger"
    assert agents["sentry"].enabled is True
    assert agents["sentry"].display_name == "Sentry"
    assert agents["trade_guard"].enabled is True
    assert agents["trade_guard"].display_name == "Trade Guard"
    assert agents["approval_canary"].enabled is False
    assert agents["approval_canary"].risk_tier == "T4"
    assert "approval.canary_t4" in agents["approval_canary"].allowed_skills
    assert agents["internet_scout"].enabled is True
    assert agents["internet_scout"].risk_tier == "T4"
    assert agents["internet_scout"].cadence == "on_demand"
    assert "internet_scout.search" in agents["internet_scout"].allowed_skills
    assert "internet_scout.deep_research" in agents["internet_scout"].allowed_skills
    assert "internet_scout.browser_task" in agents["internet_scout"].allowed_skills
    assert "internet_scout.research" in agents["internet_scout"].allowed_scopes
    assert "approval.request" in agents["internet_scout"].allowed_scopes
    assert (
        agents["internet_scout"].approval_policy["raw_web_content"]
        == "untrusted_data_only"
    )
    assert "helm_ask" in agents["internet_scout"].metadata["operator_surfaces"]
    assert "notify.send" in agents["dream_mode"].allowed_skills
    assert "notes.write_private_digest" in agents["dream_mode"].allowed_skills
    assert "notes.write" in agents["dream_mode"].allowed_scopes
    assert "notify.send" in agents["approval_triage"].allowed_skills
    assert agents["porchlight"].launch_label == "com.jarvis.alpha.porchlight"
    assert agents["porchlight"].metadata["mattermost_channel_key"] == "security_alerts"
    assert agents["porchlight"].metadata["schedule_interval_seconds"] == 86400
    assert (
        agents["porchlight"].metadata["external_boundary"]["policy_emails_source"]
        == "PORCHLIGHT_CLOUDFLARE_EXPECTED_POLICY_EMAILS"
    )
    assert agents["keyturner"].risk_tier == "T4"
    assert "secrets.rotate" in agents["keyturner"].allowed_skills
    assert agents["keyturner"].metadata["mattermost_channel_key"] == "security_alerts"
    assert agents["warden"].metadata["managed_agents"] == [
        "porchlight",
        "keyturner",
        "sweep",
        "tripwire",
        "ledger",
        "sentry",
        "trade_guard",
    ]
    assert (
        agents["warden"].metadata["active_network_hardening"]
        == "service_tls_cert_renewal"
    )
    assert agents["warden"].metadata["supervision_interval_seconds"] == 600
    assert "weekly_security_brief" in agents["warden"].metadata["capabilities"]
    assert "owner_routing" in agents["warden"].metadata["capabilities"]
    assert (
        agents["warden"].metadata["remediation_policy"]["T4_T5"]
        == "route_to_owner_with_approval"
    )
    authority = agents["warden"].metadata["authority_model"]
    assert authority["no_autonomous_trade_execution"] is True
    assert "trade_guard" in authority["observe_only"]
    assert "keyturner" in authority["approval_required"]
    assert authority["financial_remediation"] == (
        "route_to_trade_guard_then_operator_approval"
    )
    assert agents["sweep"].metadata["active_hardening"] == "service_tls_cert_renewal"
    assert (
        agents["sweep"].metadata["cert_renewal"]["launch_label"]
        == "com.jarvis.alpha.sweep-cert-renewal.*"
    )
    assert "service_tls_certs" in agents["sweep"].metadata["monitors"]
    assert "unifi_tls_pin" in agents["sweep"].metadata["monitors"]
    assert agents["tripwire"].metadata["warden_role"] == "honeypot_sensor"
    assert agents["tripwire"].metadata["mattermost_channel_key"] == "security_alerts"
    assert "honeypot_hits" in agents["tripwire"].metadata["monitors"]
    assert "source_reputation_enrichment" in agents["tripwire"].metadata["capabilities"]
    assert "repeated_probe_clustering" in agents["tripwire"].metadata["capabilities"]
    assert agents["ledger"].metadata["warden_role"] == "evidence_reporter"
    assert agents["ledger"].metadata["mattermost_channel_key"] == "security_alerts"
    assert "evidence.package_report" in agents["ledger"].allowed_skills
    assert "security_event_packaging" in agents["ledger"].metadata["capabilities"]
    assert agents["sentry"].metadata["warden_role"] == "data_boundary_monitor"
    assert agents["sentry"].metadata["mattermost_channel_key"] == "security_alerts"
    assert "financial" in agents["sentry"].metadata["protected_domains"]
    assert "pii_log_boundary" in agents["sentry"].metadata["monitors"]
    assert "sentry.boundary_inventory" in agents["sentry"].allowed_skills
    assert agents["trade_guard"].risk_tier == "T4"
    assert agents["trade_guard"].metadata["warden_role"] == "trading_safety_monitor"
    assert agents["trade_guard"].metadata["enforcement"] == "planned_not_active"
    assert agents["trade_guard"].approval_policy["trade_execution"] == "blocked"
    assert "financial" in agents["trade_guard"].metadata["protected_domains"]
    assert "kill_switch_health" in agents["trade_guard"].metadata["monitors"]
    assert (
        "pre_trade_limits_must_exist"
        in agents["trade_guard"].metadata["enforcement_gates"]
    )
    assert (
        "no_mock_approvals_in_paper_or_live"
        in agents["trade_guard"].metadata["enforcement_gates"]
    )
    assert (
        "operator_live_money_approval"
        in agents["trade_guard"].metadata["promotion_blockers"]
    )
    assert "trade_guard.kill_switch_review" in agents["trade_guard"].allowed_skills
    assert "evidence.package_report" in skills
    assert skills["evidence.package_report"].status == "planned"
    assert skills["evidence.package_report"].metadata["owner_agent"] == "ledger"
    saved_skills = {
        "dependencies.scan": "porchlight",
        "cloudflare.policy_drift": "porchlight",
        "github.branch_protection_drift": "porchlight",
        "unifi.quarantine_recommendation": "sweep",
        "unifi.firmware_drift": "sweep",
        "unifi.wan_failover_health": "sweep",
        "keyturner.oauth_health": "keyturner",
        "keyturner.rotation_dry_run": "keyturner",
        "keyturner.secrets_forecast": "keyturner",  # pragma: allowlist secret
        "tripwire.source_reputation": "tripwire",
        "tripwire.probe_clustering": "tripwire",
        "warden.weekly_brief": "warden",
        "warden.auto_ticket": "warden",
        "warden.owner_routing": "warden",
        "sentry.boundary_inventory": "sentry",
        "sentry.cross_system_flow_review": "sentry",
        "sentry.pii_log_boundary_scan": "sentry",
        "trade_guard.mode_boundary_review": "trade_guard",
        "trade_guard.kill_switch_review": "trade_guard",
        "trade_guard.order_path_boundary_review": "trade_guard",
        "trade_guard.broker_credential_review": "trade_guard",
    }
    for skill_name, owner_agent in saved_skills.items():
        assert skills[skill_name].status == "planned"
        assert skills[skill_name].metadata["owner_agent"] == owner_agent
        assert skills[skill_name].metadata["saved_for_later"] is True
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
            display_name="Sweep",
            purpose="bad id",
            risk_tier="T1",
        )


def test_agent_cost_cap_cannot_be_negative():
    with pytest.raises(ValidationError):
        AgentSpec(
            agent_id="sweep",
            display_name="Sweep",
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
        "agent_id": "sweep",
        "display_name": "Sweep",
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

    assert out.agent_id == "sweep"
    assert out.allowed_skills == ["unifi.wan_status", "unifi.clients"]
    assert out.cost_daily_cap_usd == 0.0


def test_agent_enable_disable_routes_are_t5_admin_control_plane():
    enable_classes = classify_route("POST", "/v1/agents/sweep/enable")
    disable_classes = classify_route("POST", "/v1/agents/sweep/disable")
    legacy_enable_classes = classify_route("POST", "/v1/agents/network_watchdog/enable")

    assert determine_risk_tier(enable_classes) == "T5"
    assert determine_risk_tier(disable_classes) == "T5"
    assert determine_risk_tier(legacy_enable_classes) == "T5"


def test_keyturner_rotation_route_lets_skillrunner_own_approval():
    classes = classify_route("POST", "/v1/security/rotate-key")

    assert "keyturner_rotate" in classes
    assert "admin" not in classes
    assert determine_risk_tier(classes) == "T2"
