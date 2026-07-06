-- Migration: 20260702_213000_agent_board_delegation_skill
-- Purpose:   Register governed Agent Board delegation as a metadata-only skill.
--            Delegation queues child board items; it does not execute agents.

INSERT INTO public.alpha_skill_registry
    (skill_name, domain, action, description, approval_tier, scope, status,
     mutates_state, body_access, idempotency_required, metadata)
VALUES
    ('agent_board.delegate_item', 'agent_board', 'delegate_item',
     'Split a governed Agent Board work item into role-specific child items with isolated context and output contracts.',
     'T2', 'agents.write', 'active',
     TRUE, FALSE, TRUE,
     '{
        "manifest": {
          "manifest_version": 1,
          "data_classification": "ops",
          "side_effect_class": "control_plane",
          "input_schema_ref": "registry://schemas/agent-board/delegation-v1",
          "output_schema_ref": "registry://schemas/agent-board/delegation-result-v1",
          "runtime": {"timeout_s": 10, "retry_policy": "idempotent_retry_once", "rate_limit": "30/minute/operator"},
          "cost": {"mode": "none", "max_usd_per_call": 0.0, "model_policy": null},
          "egress": {"mode": "none", "provider": null, "allowed_hosts": []},
          "audit": {"event_name": "agent_board.delegate_item", "redact_fields": ["body", "secret", "token"]},
          "compensation": "cancel_delegated_child_items",
          "test_ref": "tests/test_agent_board.py",
          "runbook_ref": "docs/JARVIS_Alpha_Skills_Agents_Catalog_v0_9.md"
        },
        "execution_path": "fastapi_route",
        "operator_surface": "helm",
        "delegation_model": "board_child_items",
        "queues_agent_board_items": true,
        "does_not_execute_agents": true,
        "output_contract_required": true,
        "discovery": {
          "mapping_source": "20260702_213000_agent_board_delegation_skill",
          "codex_skill_refs": [
            {
              "name": "production",
              "ref": "codex://skills/production/SKILL.md",
              "status": "mapped",
              "description": "Delegated work still needs readiness gates before deploy or external action."
            }
          ],
          "agentfs_refs": [
            {
              "name": "delegation_handoff",
              "ref": "agentfs://runs/{run_id}/outputs/delegation-handoff.json",
              "status": "available",
              "description": "Delegated subagent outputs should be written as governed AgentFS handoff artifacts.",
              "metadata": {
                "artifact_table": "public.alpha_agent_run_artifacts",
                "stores_skill_file_bodies": false
              }
            }
          ]
        }
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
         WHERE skill_name = 'agent_board.delegate_item'
           AND status = 'active'
           AND metadata->>'delegation_model' = 'board_child_items'
           AND metadata->>'does_not_execute_agents' = 'true'
    ) THEN
        RAISE EXCEPTION 'POST-FLIGHT agent board delegation skill seed FAILED';
    END IF;

    RAISE NOTICE 'POST-FLIGHT agent board delegation skill OK';
END $$;
