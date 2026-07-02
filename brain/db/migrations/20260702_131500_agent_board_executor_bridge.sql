-- Migration: 20260702_131500_agent_board_executor_bridge
-- Purpose:   Register the Agent Board -> TaskGraph executor bridge as a
--            governed Alpha skill. The route reuses existing task graph tables
--            and approval gates; it does not introduce a new executor runtime.

INSERT INTO public.alpha_skill_registry
    (skill_name, domain, action, description, approval_tier, scope, status,
     mutates_state, body_access, idempotency_required, metadata)
VALUES
    ('agent_board.dispatch_item', 'agent_board', 'dispatch_item',
     'Bridge an approved Agent Board work item into a TaskGraph and wake the existing executor.',
     'T2', 'agents.write', 'active',
     TRUE, FALSE, TRUE,
     '{
        "manifest": {
          "manifest_version": 1,
          "data_classification": "ops",
          "side_effect_class": "control_plane",
          "input_schema_ref": "registry://schemas/agent-board/task-graph-dispatch-v1",
          "output_schema_ref": "registry://schemas/agent-board/task-graph-dispatch-result-v1",
          "runtime": {"timeout_s": 10, "retry_policy": "idempotent_retry_once", "rate_limit": "30/minute/operator"},
          "cost": {"mode": "none", "max_usd_per_call": 0.0, "model_policy": null},
          "egress": {"mode": "none", "provider": null, "allowed_hosts": []},
          "audit": {"event_name": "agent_board.dispatch_item", "redact_fields": ["body", "secret", "token"]},
          "compensation": "cancel_task_graph_and_work_item",
          "test_ref": "tests/test_agent_board.py",
          "runbook_ref": "docs/JARVIS_Alpha_Skills_Agents_Catalog_v0_9.md"
        },
        "execution_path": "fastapi_route",
        "operator_surface": "helm",
        "executor_bridge": "task_graph",
        "approval_gate": "alpha_task_steps.approval_required",
        "wakes_executor": true
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
         WHERE skill_name = 'agent_board.dispatch_item'
           AND status = 'active'
           AND metadata->>'executor_bridge' = 'task_graph'
    ) THEN
        RAISE EXCEPTION 'POST-FLIGHT agent board executor bridge skill seed FAILED';
    END IF;

    RAISE NOTICE 'POST-FLIGHT agent board executor bridge skill OK';
END $$;
