-- Add a progress heartbeat so the dispatcher's stale_running_minutes guard can
-- distinguish a genuinely hung job from a slow-but-alive one. Bumped on claim
-- and on every update_progress(). Runs with search_path = app_jobs, public.

BEGIN;

ALTER TABLE jobs ADD COLUMN IF NOT EXISTS last_progress_at timestamptz;

COMMIT;
