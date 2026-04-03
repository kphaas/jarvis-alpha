-- 004_dev_agent.sql — Dev agent: alpha_task_graphs approved status + alpha_projects

BEGIN;

ALTER TABLE alpha_task_graphs DROP CONSTRAINT IF EXISTS alpha_task_graphs_status_check;
ALTER TABLE alpha_task_graphs ADD CONSTRAINT alpha_task_graphs_status_check
  CHECK (status IN ('pending','running','approved','paused','completed','failed'));

CREATE TABLE IF NOT EXISTS alpha_projects (
  id          SERIAL PRIMARY KEY,
  name        TEXT NOT NULL,
  project_type TEXT NOT NULL CHECK (project_type IN ('forge','personal','problem')),
  repo_slug   TEXT,
  created_at  TIMESTAMPTZ DEFAULT now()
);

INSERT INTO alpha_projects (name, project_type, repo_slug)
SELECT 'jarvis-alpha', 'forge', 'kphaas/jarvis-alpha'
WHERE NOT EXISTS (SELECT 1 FROM alpha_projects);

COMMIT;
