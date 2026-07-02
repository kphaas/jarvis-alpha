-- Rollback: 20260702_213000_agent_board_delegation_skill

DELETE FROM public.alpha_skill_registry
 WHERE skill_name = 'agent_board.delegate_item';
