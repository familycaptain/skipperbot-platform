-- =============================================================================
-- Goals app — 002_migrate_from_public.sql
-- =============================================================================
-- One-shot data migration: moves goals/projects/tasks rows from the legacy
-- public schema (pre-packaging Skipperbot) into the app_goals schema
-- created by 001_initial.sql.
--
-- Idempotent:
--   - Each INSERT uses ON CONFLICT (id) DO NOTHING so re-running won't
--     duplicate or overwrite.
--   - Each table-copy is wrapped in a DO block that checks if the source
--     public.<table> exists. On a fresh install (no legacy data) those
--     blocks no-op silently — there's nothing to migrate.
--
-- Does NOT drop the source tables. After this migration completes and
-- you've verified your data is intact in app_goals.*, you may manually
-- drop the legacy public.goals/projects/tasks (instructions printed by
-- 003_drop_public_after_verify.sql, which is the optional companion step
-- you run by hand after cutover).
--
-- Runs in a single transaction so a failure (e.g. column mismatch)
-- rolls back the whole thing.

BEGIN;

SET LOCAL search_path TO app_goals, public;

-- ---------------------------------------------------------------------------
-- 1. goals
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    source_rows int := 0;
    target_rows_before int := 0;
    target_rows_after int := 0;
    inserted int := 0;
BEGIN
    -- Skip silently if there's nothing to migrate (fresh install case).
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'goals'
    ) THEN
        RAISE NOTICE 'goals: no public.goals — fresh install, skipping';
        RETURN;
    END IF;

    SELECT COUNT(*) INTO source_rows FROM public.goals;
    SELECT COUNT(*) INTO target_rows_before FROM app_goals.goals;

    INSERT INTO app_goals.goals (
        id, name, owners, collaborators, target_date, status, stack_rank,
        notes, definition_of_done, history, artifacts, created_by, created_at
    )
    SELECT
        id, name, owners, COALESCE(collaborators, '{}'::text[]),
        target_date, status, stack_rank, notes,
        COALESCE(definition_of_done, ''), history, artifacts,
        created_by, created_at
    FROM public.goals
    ON CONFLICT (id) DO NOTHING;

    SELECT COUNT(*) INTO target_rows_after FROM app_goals.goals;
    inserted := target_rows_after - target_rows_before;

    RAISE NOTICE 'goals: source=% before=% after=% inserted=%',
        source_rows, target_rows_before, target_rows_after, inserted;

    -- Sanity: every source row should now exist in target (either pre-existed
    -- or was just inserted). Equivalently, target_rows_after >= source_rows.
    IF target_rows_after < source_rows THEN
        RAISE EXCEPTION
            'goals migration sanity check failed: source=% target=%',
            source_rows, target_rows_after;
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 2. projects (depends on goals existing for the FK)
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    source_rows int := 0;
    target_rows_before int := 0;
    target_rows_after int := 0;
    inserted int := 0;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'projects'
    ) THEN
        RAISE NOTICE 'projects: no public.projects — fresh install, skipping';
        RETURN;
    END IF;

    SELECT COUNT(*) INTO source_rows FROM public.projects;
    SELECT COUNT(*) INTO target_rows_before FROM app_goals.projects;

    INSERT INTO app_goals.projects (
        id, name, goal_id, owners, due_date, priority, status, stack_rank,
        notes, definition_of_done, pm_cadence_minutes, history, artifacts,
        auto_nag, trello, created_by, created_at
    )
    SELECT
        id, name, goal_id, owners, due_date, priority, status, stack_rank,
        notes, COALESCE(definition_of_done, ''), pm_cadence_minutes,
        history, artifacts, auto_nag, trello, created_by, created_at
    FROM public.projects
    ON CONFLICT (id) DO NOTHING;

    SELECT COUNT(*) INTO target_rows_after FROM app_goals.projects;
    inserted := target_rows_after - target_rows_before;

    RAISE NOTICE 'projects: source=% before=% after=% inserted=%',
        source_rows, target_rows_before, target_rows_after, inserted;

    IF target_rows_after < source_rows THEN
        RAISE EXCEPTION
            'projects migration sanity check failed: source=% target=%',
            source_rows, target_rows_after;
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 3. tasks (depends on projects + self via parent_task_id)
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    source_rows int := 0;
    target_rows_before int := 0;
    target_rows_after int := 0;
    inserted int := 0;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'tasks'
    ) THEN
        RAISE NOTICE 'tasks: no public.tasks — fresh install, skipping';
        RETURN;
    END IF;

    SELECT COUNT(*) INTO source_rows FROM public.tasks;
    SELECT COUNT(*) INTO target_rows_before FROM app_goals.tasks;

    INSERT INTO app_goals.tasks (
        id, name, project_id, parent_task_id, assigned_to, due_date,
        priority, status, stack_rank, depends_on, trello_card_id,
        trello_list, trello_linked, notes, definition_of_done,
        history, artifacts, created_by, created_at
    )
    SELECT
        id, name, project_id, parent_task_id, assigned_to, due_date,
        priority, status, stack_rank, depends_on, trello_card_id,
        trello_list, trello_linked, notes, COALESCE(definition_of_done, ''),
        history, artifacts, created_by, created_at
    FROM public.tasks
    ON CONFLICT (id) DO NOTHING;

    SELECT COUNT(*) INTO target_rows_after FROM app_goals.tasks;
    inserted := target_rows_after - target_rows_before;

    RAISE NOTICE 'tasks: source=% before=% after=% inserted=%',
        source_rows, target_rows_before, target_rows_after, inserted;

    IF target_rows_after < source_rows THEN
        RAISE EXCEPTION
            'tasks migration sanity check failed: source=% target=%',
            source_rows, target_rows_after;
    END IF;
END $$;

COMMIT;

-- =============================================================================
-- After this migration:
--   - app_goals.goals/projects/tasks contains a copy of every row that was
--     in public.goals/projects/tasks.
--   - The public.* tables are UNTOUCHED. They still hold the legacy rows.
--   - app.py + apps/goals/data.py both read from app_goals.* from now on.
--
-- Verify your data, then optionally drop the legacy tables to reclaim
-- the row-count clarity:
--
--   psql -d skipperbot -c "
--     -- destructive: requires explicit acknowledgement
--     -- BEGIN;
--     -- DROP TABLE public.tasks CASCADE;     -- drops dependent FKs first
--     -- DROP TABLE public.projects CASCADE;
--     -- DROP TABLE public.goals CASCADE;
--     -- COMMIT;
--   "
--
-- We don't drop them here on purpose — Stage 1 cutover happens against a
-- copy of prod, so the user gets to confirm everything works before
-- losing the legacy rows.
-- =============================================================================
