-- Migration: 20260606_105000_trade_guard_foundation
-- Purpose:   Register Trade Guard as Warden's read-only trading safety monitor.
--            This adds no broker powers, order hooks, or autonomous remediation.

INSERT INTO public.alpha_skill_registry
    (skill_name, domain, action, description, approval_tier, scope, status,
     mutates_state, body_access, idempotency_required, metadata)
VALUES
    ('trade_guard.mode_boundary_review', 'trade_guard', 'mode_boundary_review',
     'Review Financial paper/live mode separation and broker environment boundaries without changing trading state.',
     'T1', 'security.read', 'planned', FALSE, FALSE, FALSE,
     '{"owner_agent": "trade_guard", "saved_for_later": true}'::jsonb),
    ('trade_guard.kill_switch_review', 'trade_guard', 'kill_switch_review',
     'Review Financial kill-switch, halt-signal, and approval-gate health without changing halt state.',
     'T1', 'security.read', 'planned', FALSE, FALSE, FALSE,
     '{"owner_agent": "trade_guard", "saved_for_later": true}'::jsonb),
    ('trade_guard.order_path_boundary_review', 'trade_guard', 'order_path_boundary_review',
     'Review order-path boundaries for pre-trade approvals, spend caps, and execution isolation without placing orders.',
     'T1', 'security.read', 'planned', FALSE, FALSE, FALSE,
     '{"owner_agent": "trade_guard", "saved_for_later": true}'::jsonb),
    ('trade_guard.broker_credential_review', 'trade_guard', 'broker_credential_review',
     'Review broker credential exposure posture and rotation evidence without reading secret values or rotating keys.',
     'T1', 'security.read', 'planned', FALSE, FALSE, FALSE,
     '{"owner_agent": "trade_guard", "saved_for_later": true}'::jsonb)
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
    metadata = public.alpha_skill_registry.metadata || EXCLUDED.metadata,
    updated_at = NOW();

INSERT INTO public.alpha_agents
    (agent_id, display_name, purpose, risk_tier, status, enabled, cadence,
     launch_label, allowed_skills, allowed_scopes, cost_daily_cap_usd,
     approval_policy, model_policy, metadata)
VALUES
    ('trade_guard', 'Trade Guard',
     'Monitor trading safety boundaries for Financial before any paper or live trading enforcement is delegated.',
     'T4', 'active', TRUE, 'on_demand', NULL,
     ARRAY[
       'trade_guard.mode_boundary_review',
       'trade_guard.kill_switch_review',
       'trade_guard.order_path_boundary_review',
       'trade_guard.broker_credential_review',
       'notify.send'
     ],
     ARRAY[
       'security.read',
       'agents.read',
       'evidence.read',
       'notify.send'
     ],
     0.0,
     '{"writes": "blocked", "remediation": "warden_approval_required", "trade_execution": "blocked"}'::jsonb,
     '{}'::jsonb,
     '{
        "mattermost_channel_key": "security_alerts",
        "manual_run_enabled": false,
        "warden_managed": true,
        "warden_role": "trading_safety_monitor",
        "protected_domains": [
          "financial",
          "alpha",
          "brain"
        ],
        "monitors": [
          "paper_live_mode_boundary",
          "kill_switch_health",
          "halt_signal_health",
          "pre_trade_approval_gate",
          "spend_cap_boundary",
          "broker_credential_exposure",
          "order_execution_isolation"
        ],
        "controls": [
          "read_only_review",
          "no_order_placement",
          "no_broker_mutation",
          "warden_approval_required_for_remediation"
        ],
        "capabilities": [
          "mode_boundary_review",
          "kill_switch_review",
          "order_path_boundary_review",
          "broker_credential_review"
        ],
        "planned_skills": [
          "trade_guard.mode_boundary_review",
          "trade_guard.kill_switch_review",
          "trade_guard.order_path_boundary_review",
          "trade_guard.broker_credential_review"
        ],
        "remediation": "approval_only",
        "enforcement": "planned_not_active"
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

UPDATE public.alpha_agents
SET metadata = jsonb_set(
    jsonb_set(
      jsonb_set(
        metadata,
        '{managed_agents}',
        (
          SELECT jsonb_agg(DISTINCT item)
          FROM jsonb_array_elements_text(
            COALESCE(metadata->'managed_agents', '[]'::jsonb) ||
            '["trade_guard"]'::jsonb
          ) AS t(item)
        ),
        true
      ),
      '{agent_roles}',
      COALESCE(metadata->'agent_roles', '{}'::jsonb)
      || '{"trade_guard": "trading_safety_monitor"}'::jsonb,
      true
    ),
    '{active_security_capabilities}',
    (
      SELECT jsonb_agg(DISTINCT item)
      FROM jsonb_array_elements_text(
        COALESCE(metadata->'active_security_capabilities', '[]'::jsonb) ||
        '[
          "trade_guard_mode_boundary_review",
          "trade_guard_kill_switch_review",
          "trade_guard_order_path_boundary_review",
          "trade_guard_broker_credential_review"
        ]'::jsonb
      ) AS t(item)
    ),
    true
)
WHERE agent_id = 'warden';

DO $$
DECLARE
    v_trade_guard jsonb;
    v_warden jsonb;
BEGIN
    SELECT metadata INTO v_trade_guard
    FROM public.alpha_agents
    WHERE agent_id = 'trade_guard';

    SELECT metadata INTO v_warden
    FROM public.alpha_agents
    WHERE agent_id = 'warden';

    IF v_trade_guard IS NULL
       OR v_warden IS NULL
       OR v_trade_guard->>'warden_role' != 'trading_safety_monitor'
       OR v_trade_guard->>'enforcement' != 'planned_not_active'
       OR NOT (v_trade_guard->'protected_domains' ? 'financial')
       OR NOT (v_warden->'managed_agents' ? 'trade_guard')
       OR NOT (v_warden->'active_security_capabilities' ? 'trade_guard_kill_switch_review') THEN
        RAISE EXCEPTION 'POST-FLIGHT trade guard foundation registration FAILED';
    END IF;

    RAISE NOTICE 'POST-FLIGHT trade guard foundation registration OK';
END $$;
