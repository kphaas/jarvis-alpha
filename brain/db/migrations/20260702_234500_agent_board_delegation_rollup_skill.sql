-- Migration: 20260702_234500_agent_board_delegation_rollup_skill
-- Purpose:   Register delegated child completion roll-up as a governed skill.

INSERT INTO public.alpha_skill_registry
    (skill_name, domain, action, description, approval_tier, scope, status,
     mutates_state, body_access, idempotency_required, metadata)
VALUES
    ('agent_board.rollup_delegation', 'agent_board', 'rollup_delegation',
     'Roll delegated child work item results into a parent Agent Board handoff with TaskGraph output references.',
     'T2', 'agents.write', 'active',
     TRUE, FALSE, TRUE,
     '{
        "manifest": {
          "manifest_version": 1,
          "data_classification": "ops",
          "side_effect_class": "control_plane",
          "input_schema_ref": "registry://schemas/agent-board/delegation-rollup-v1",
          "output_schema_ref": "registry://schemas/agent-board/delegation-rollup-result-v1",
          "runtime": {"timeout_s": 10, "retry_policy": "idempotent_retry_once", "rate_limit": "30/minute/operator"},
          "cost": {"mode": "none", "max_usd_per_call": 0.0, "model_policy": null},
          "egress": {"mode": "none", "provider": null, "allowed_hosts": []},
          "audit": {"event_name": "agent_board.rollup_delegation", "redact_fields": ["body", "secret", "token"]},
          "compensation": "status_change_event_trail",
          "test_ref": "tests/test_agent_board_rollup.py",
          "runbook_ref": "docs/JARVIS_Alpha_Skills_Agents_Catalog_v0_9.md"
        },
        "execution_path": "fastapi_route",
        "executor_hook": "task_graph_completion",
        "operator_surface": "helm",
        "delegation_model": "board_child_items",
        "handoff_artifact_refs": "task_graph_step_outputs",
        "rolls_up_to_parent": true,
        "does_not_execute_agents": true
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

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM public.alpha_skill_registry
         WHERE skill_name = 'agent_board.rollup_delegation'
           AND status = 'active'
           AND metadata->>'rolls_up_to_parent' = 'true'
           AND metadata->>'does_not_execute_agents' = 'true'
    ) THEN
        RAISE EXCEPTION 'POST-FLIGHT delegation roll-up skill seed FAILED';
    END IF;

    RAISE NOTICE 'POST-FLIGHT delegation roll-up skill OK';
END $$;
