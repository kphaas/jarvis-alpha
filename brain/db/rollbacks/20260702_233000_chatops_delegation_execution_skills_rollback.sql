-- Rollback: 20260702_233000_chatops_delegation_execution_skills

DELETE FROM public.alpha_skill_registry
 WHERE skill_name IN (
    'chatops.agent_board_control',
    'agent_board.dispatch_delegation'
 );
