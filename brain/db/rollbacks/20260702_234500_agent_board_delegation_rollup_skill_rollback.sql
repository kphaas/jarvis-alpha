-- Rollback: 20260702_234500_agent_board_delegation_rollup_skill

DELETE FROM public.alpha_skill_registry
 WHERE skill_name = 'agent_board.rollup_delegation';
