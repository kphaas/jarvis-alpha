-- Rollback: 20260625_130000_agent_board_work_queue
-- Purpose:  Remove Alpha Agent Board work queue primitives and seeded board
--           capabilities.

DELETE FROM public.alpha_skill_registry
 WHERE skill_name IN (
    'agent_board.read',
    'agent_board.queue_item',
    'agent_board.update_status'
 );

DROP TABLE IF EXISTS public.alpha_agent_work_item_events;
DROP TABLE IF EXISTS public.alpha_agent_work_items;
