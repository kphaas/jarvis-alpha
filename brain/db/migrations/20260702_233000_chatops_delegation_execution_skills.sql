-- Migration: 20260702_233000_chatops_delegation_execution_skills
-- Purpose:   Register ChatOps board controls and delegated child dispatch.

INSERT INTO public.alpha_skill_registry
    (skill_name, domain, action, description, approval_tier, scope, status,
     mutates_state, body_access, idempotency_required, metadata)
VALUES
    ('chatops.agent_board_control', 'chatops', 'agent_board_control',
     'Handle token-authenticated Mattermost Agent Board queue, status, and handoff commands.',
     'T2', 'chatops.write', 'active',
     TRUE, FALSE, TRUE,
     '{
        "manifest": {
          "manifest_version": 1,
          "data_classification": "ops",
          "side_effect_class": "control_plane",
          "input_schema_ref": "registry://schemas/chatops/agent-board-control-v1",
          "output_schema_ref": "registry://schemas/chatops/agent-board-control-result-v1",
          "runtime": {"timeout_s": 10, "retry_policy": "idempotent_retry_once", "rate_limit": "20/minute/operator"},
          "cost": {"mode": "none", "max_usd_per_call": 0.0, "model_policy": null},
          "egress": {"mode": "local", "provider": "mattermost", "allowed_hosts": []},
          "audit": {"event_name": "chatops.agent_board_control", "redact_fields": ["token", "secret"]},
          "compensation": "status_change_event_trail",
          "test_ref": "tests/test_agent_events_chatops.py",
          "runbook_ref": "docs/JARVIS_Alpha_Skills_Agents_Catalog_v0_9.md"
        },
        "surface": "mattermost",
        "execution_path": "fastapi_route",
        "operator_surface": "chatops",
        "commands": ["board", "board blocked", "board needs-me", "board queue", "board approve-handoff"],
        "does_not_bypass_alpha_gates": true
      }'::jsonb),
    ('agent_board.dispatch_delegation', 'agent_board', 'dispatch_delegation',
     'Dispatch delegated child Agent Board work items into TaskGraphs and record parent roll-up metadata.',
     'T2', 'agents.write', 'active',
     TRUE, FALSE, TRUE,
     '{
        "manifest": {
          "manifest_version": 1,
          "data_classification": "ops",
          "side_effect_class": "control_plane",
          "input_schema_ref": "registry://schemas/agent-board/delegation-dispatch-v1",
          "output_schema_ref": "registry://schemas/agent-board/delegation-dispatch-result-v1",
          "runtime": {"timeout_s": 20, "retry_policy": "idempotent_retry_once", "rate_limit": "20/minute/operator"},
          "cost": {"mode": "none", "max_usd_per_call": 0.0, "model_policy": null},
          "egress": {"mode": "none", "provider": null, "allowed_hosts": []},
          "audit": {"event_name": "agent_board.dispatch_delegation", "redact_fields": ["body", "secret", "token"]},
          "compensation": "cancel_child_task_graphs_and_parent_work_item",
          "test_ref": "tests/test_agent_board.py",
          "runbook_ref": "docs/JARVIS_Alpha_Skills_Agents_Catalog_v0_9.md"
        },
        "execution_path": "fastapi_route",
        "operator_surface": "helm",
        "delegation_model": "board_child_items",
        "executor_bridge": "task_graph",
        "approval_gate": "alpha_task_steps.approval_required",
        "wakes_executor": true,
        "rolls_up_to_parent": true
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
         WHERE skill_name = 'chatops.agent_board_control'
           AND status = 'active'
           AND metadata->>'does_not_bypass_alpha_gates' = 'true'
    ) THEN
        RAISE EXCEPTION 'POST-FLIGHT ChatOps board control skill seed FAILED';
    END IF;

    IF NOT EXISTS (
        SELECT 1
          FROM public.alpha_skill_registry
         WHERE skill_name = 'agent_board.dispatch_delegation'
           AND status = 'active'
           AND metadata->>'wakes_executor' = 'true'
           AND metadata->>'rolls_up_to_parent' = 'true'
    ) THEN
        RAISE EXCEPTION 'POST-FLIGHT delegation dispatch skill seed FAILED';
    END IF;

    RAISE NOTICE 'POST-FLIGHT ChatOps delegation execution skills OK';
END $$;
