-- Rollback: 20260702_140000_agent_scheduled_work
-- Purpose:  Remove governed Agent Board scheduled work primitives.

DELETE FROM public.alpha_skill_registry
 WHERE skill_name IN (
    'agent_schedule.read',
    'agent_schedule.create',
    'agent_schedule.materialize_due'
 );

DROP TRIGGER IF EXISTS trg_agent_scheduled_work_updated ON public.alpha_agent_scheduled_work;
DROP TABLE IF EXISTS public.alpha_agent_scheduled_work_runs;
DROP TABLE IF EXISTS public.alpha_agent_scheduled_work;
