-- =============================================================================
-- Todo app — 002_migrate_from_public.sql
-- =============================================================================
-- One-shot data migration: moves todo_config rows from the legacy public
-- schema (pre-packaging Skipperbot) into the app_todo schema created by
-- 001_initial.sql.
--
-- Idempotent:
--   - INSERT uses ON CONFLICT (user_id) DO NOTHING so re-running won't
--     duplicate or overwrite.
--   - Wrapped in a DO block that checks if the source public.todo_config
--     exists. On a fresh install (no legacy data) the block no-ops
--     silently — there's nothing to migrate.
--
-- Does NOT drop the source table. After this migration completes and
-- you've verified your data is intact in app_todo.todo_config, you may
-- manually drop the legacy public.todo_config (instructions at the
-- bottom of this file).
--
-- Runs in a single transaction so a failure (e.g. column mismatch)
-- rolls back the whole thing.

BEGIN;

SET LOCAL search_path TO app_todo, public;

-- ---------------------------------------------------------------------------
-- todo_config
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    source_rows int := 0;
    target_rows_before int := 0;
    target_rows_after int := 0;
    inserted int := 0;
    has_backlog boolean := false;
BEGIN
    -- Skip silently if there's nothing to migrate (fresh install case).
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'todo_config'
    ) THEN
        RAISE NOTICE 'todo_config: no public.todo_config — fresh install, skipping';
        RETURN;
    END IF;

    -- backlog_list_id was added in migration 060; very old installs may not have it.
    SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name   = 'todo_config'
          AND column_name  = 'backlog_list_id'
    ) INTO has_backlog;

    SELECT COUNT(*) INTO source_rows FROM public.todo_config;
    SELECT COUNT(*) INTO target_rows_before FROM app_todo.todo_config;

    IF has_backlog THEN
        INSERT INTO app_todo.todo_config (
            user_id, default_list_id, backlog_list_id,
            nudge_enabled, nudge_day, nudge_time, show_on_calendar,
            created_at, updated_at
        )
        SELECT
            user_id, default_list_id, backlog_list_id,
            nudge_enabled, nudge_day, nudge_time,
            COALESCE(show_on_calendar, true),
            created_at, updated_at
        FROM public.todo_config
        ON CONFLICT (user_id) DO NOTHING;
    ELSE
        -- Legacy install without backlog_list_id — back-fill NULL.
        INSERT INTO app_todo.todo_config (
            user_id, default_list_id, backlog_list_id,
            nudge_enabled, nudge_day, nudge_time, show_on_calendar,
            created_at, updated_at
        )
        SELECT
            user_id, default_list_id, NULL::text,
            nudge_enabled, nudge_day, nudge_time,
            COALESCE(show_on_calendar, true),
            created_at, updated_at
        FROM public.todo_config
        ON CONFLICT (user_id) DO NOTHING;
    END IF;

    SELECT COUNT(*) INTO target_rows_after FROM app_todo.todo_config;
    inserted := target_rows_after - target_rows_before;

    RAISE NOTICE 'todo_config: source=% before=% after=% inserted=% (backlog_present=%)',
        source_rows, target_rows_before, target_rows_after, inserted, has_backlog;

    IF target_rows_after < source_rows THEN
        RAISE EXCEPTION
            'todo_config migration sanity check failed: source=% target=%',
            source_rows, target_rows_after;
    END IF;
END $$;

COMMIT;

-- =============================================================================
-- After this migration:
--   - app_todo.todo_config contains a copy of every row that was in
--     public.todo_config.
--   - public.todo_config is UNTOUCHED. It still holds the legacy rows.
--   - apps/todo/data.py reads from app_todo.* from now on.
--
-- Verify your data, then optionally drop the legacy table to reclaim
-- the row-count clarity:
--
--   psql -d skipperbot -c "
--     -- destructive: requires explicit acknowledgement
--     -- BEGIN;
--     -- DROP TABLE public.todo_config CASCADE;
--     -- COMMIT;
--   "
--
-- We don't drop it here on purpose — Stage 1 cutover happens against a
-- copy of prod, so the user gets to confirm everything works before
-- losing the legacy rows.
-- =============================================================================
