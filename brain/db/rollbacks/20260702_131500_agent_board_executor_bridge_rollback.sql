-- Rollback: 20260702_131500_agent_board_executor_bridge

DELETE FROM public.alpha_skill_registry
 WHERE skill_name = 'agent_board.dispatch_item';
