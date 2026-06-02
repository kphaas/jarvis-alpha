-- Migration: 20260602_094500_keyturner_rotation_agent
-- Purpose:   Register Keyturner as the unified owner for approved key/password
--            rotations while preserving existing rotation scripts as actuators.

INSERT INTO public.alpha_skill_registry
    (skill_name, domain, action, description, approval_tier, scope, status,
     mutates_state, body_access, idempotency_required, metadata)
VALUES
    ('secrets.rotate', 'secrets', 'rotate',
     'Rotate approved Alpha secrets and service credentials through the Keyturner workflow.',
     'T4', 'secrets.rotate', 'active',
     TRUE, FALSE, TRUE,
     '{
        "manifest": {
          "manifest_version": 1,
          "data_classification": "security",
          "side_effect_class": "control_plane",
          "input_schema_ref": "registry://schemas/skill-input/default-v1",
          "output_schema_ref": "registry://schemas/skill-output/default-v1",
          "runtime": {
            "timeout_s": 600,
            "retry_policy": "checkpointed_rollback",
            "rate_limit": "10/day/operator"
          },
          "cost": {
            "mode": "none",
            "max_usd_per_call": 0.0,
            "model_policy": null
          },
          "egress": {
            "mode": "tailscale",
            "provider": "alpha_control_plane",
            "allowed_hosts": []
          },
          "audit": {
            "event_name": "skill.invoke",
            "redact_fields": ["token", "secret", "body"]
          },
          "compensation": "restore_previous_secret_and_restart_services",
          "test_ref": "tests/test_agent_skill_registry.py",
          "runbook_ref": "docs/JARVIS_Alpha_Skills_Agents_Catalog_v0_9.md"
        },
        "execution_path": "rotation_scripts",
        "approval_required": true,
        "handled_secret_classes": ["api_key", "service_token", "admin_pin", "db_password"]
      }'::jsonb)
ON CONFLICT (skill_name) DO UPDATE
SET domain = EXCLUDED.domain,
    action = EXCLUDED.action,
    description = EXCLUDED.description,
    approval_tier = EXCLUDED.approval_tier,
    scope = EXCLUDED.scope,
    status = EXCLUDED.status,
    mutates_state = EXCLUDED.mutates_state,
    body_access = EXCLUDED.body_access,
    idempotency_required = EXCLUDED.idempotency_required,
    metadata = EXCLUDED.metadata,
    updated_at = NOW();

INSERT INTO public.alpha_agents
    (agent_id, display_name, purpose, risk_tier, status, enabled, cadence,
     launch_label, allowed_skills, allowed_scopes, cost_daily_cap_usd,
     approval_policy, model_policy, metadata)
VALUES
    ('keyturner', 'Keyturner',
     'Own approved Alpha key and password rotations across existing rotation jobs.',
     'T4', 'active', TRUE, 'on_demand', NULL,
     ARRAY['secrets.rotate', 'notify.send'],
     ARRAY['secrets.rotate', 'notify.send', 'security.read'],
     0.0,
     '{
        "writes": "approval_required",
        "api_keys": "T3",
        "service_tokens": "T3",
        "db_passwords": "T4",
        "rollback": "required"
      }'::jsonb,
     '{}'::jsonb,
     '{
        "mattermost_channel_key": "security_alerts",
        "manual_run_enabled": false,
        "rotation_config": "scripts/secrets_rotation.json",
        "existing_actuators": [
          "scripts/rotate_secret.py",
          "scripts/rotate_service_token.py",
          "launchagents/com.jarvis.alpha.rotate.*"
        ],
        "porchlight_relationship": "porchlight_detects_keyturner_remediates"
      }'::jsonb)
ON CONFLICT (agent_id) DO UPDATE
SET display_name = EXCLUDED.display_name,
    purpose = EXCLUDED.purpose,
    risk_tier = EXCLUDED.risk_tier,
    status = EXCLUDED.status,
    enabled = EXCLUDED.enabled,
    cadence = EXCLUDED.cadence,
    launch_label = EXCLUDED.launch_label,
    allowed_skills = EXCLUDED.allowed_skills,
    allowed_scopes = EXCLUDED.allowed_scopes,
    cost_daily_cap_usd = EXCLUDED.cost_daily_cap_usd,
    approval_policy = EXCLUDED.approval_policy,
    model_policy = EXCLUDED.model_policy,
    metadata = public.alpha_agents.metadata || EXCLUDED.metadata,
    updated_at = NOW();

DO $$
DECLARE
    v_skill_active boolean;
    v_agent_skill boolean;
BEGIN
    SELECT status = 'active'
    INTO v_skill_active
    FROM public.alpha_skill_registry
    WHERE skill_name = 'secrets.rotate'
      AND approval_tier = 'T4'
      AND mutates_state;

    SELECT 'secrets.rotate' = ANY(allowed_skills)
    INTO v_agent_skill
    FROM public.alpha_agents
    WHERE agent_id = 'keyturner'
      AND status = 'active'
      AND enabled;

    IF COALESCE(v_skill_active, false) IS NOT TRUE
       OR COALESCE(v_agent_skill, false) IS NOT TRUE THEN
        RAISE EXCEPTION 'POST-FLIGHT Keyturner registry seed FAILED';
    END IF;

    RAISE NOTICE 'POST-FLIGHT Keyturner registry seed OK';
END $$;
