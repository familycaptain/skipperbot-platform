-- =============================================================================
-- Schedules app — 002_migrate_from_public.sql
-- =============================================================================
-- One-shot data migration: moves schedules + schedule_completions rows
-- from the legacy public schema into the app_schedules schema created
-- by 001_initial.sql.
--
-- Idempotent:
--   - INSERT uses ON CONFLICT (id) DO NOTHING so re-running won't
--     duplicate or overwrite.
--   - Wrapped in DO blocks that check if each source table exists. On
--     a fresh install (no legacy data) the blocks no-op silently.
--
-- Does NOT drop the source tables.
--
-- Runs in a single transaction so a failure rolls back the whole thing.

BEGIN;

SET LOCAL search_path TO app_schedules, public;

-- ---------------------------------------------------------------------------
-- 1. schedules (depends on nothing within the app)
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    source_rows int := 0;
    target_rows_before int := 0;
    target_rows_after int := 0;
    inserted int := 0;
    has_job_config boolean := false;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'schedules'
    ) THEN
        RAISE NOTICE 'schedules: no public.schedules — fresh install, skipping';
        RETURN;
    END IF;

    -- job_config was added in legacy migration 062. Very old installs
    -- may not have it.
    SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'schedules'
          AND column_name  = 'job_config'
    ) INTO has_job_config;

    SELECT COUNT(*) INTO source_rows FROM public.schedules;
    SELECT COUNT(*) INTO target_rows_before FROM app_schedules.schedules;

    IF has_job_config THEN
        INSERT INTO app_schedules.schedules (
            id, title, description, category, assigned_to, created_by,
            recurrence_type, recurrence_rule, time_of_day, duration_mins,
            usage_metric, usage_interval,
            last_completed, next_due, completed_count,
            linked_entity_id, linked_entity_type,
            reminder_mins, notify_channel, job_config,
            active, created_at, updated_at
        )
        SELECT
            id, title, COALESCE(description, ''), COALESCE(category, 'general'),
            COALESCE(assigned_to, ''), created_by,
            COALESCE(recurrence_type, 'weekly'),
            COALESCE(recurrence_rule, '{}'::jsonb),
            time_of_day, duration_mins,
            usage_metric, usage_interval,
            last_completed, next_due, COALESCE(completed_count, 0),
            linked_entity_id, linked_entity_type,
            COALESCE(reminder_mins, 60), COALESCE(notify_channel, 'both'),
            COALESCE(job_config, '{}'::jsonb),
            COALESCE(active, true), created_at, updated_at
        FROM public.schedules
        ON CONFLICT (id) DO NOTHING;
    ELSE
        -- Legacy pre-062 install — back-fill job_config = '{}'.
        INSERT INTO app_schedules.schedules (
            id, title, description, category, assigned_to, created_by,
            recurrence_type, recurrence_rule, time_of_day, duration_mins,
            usage_metric, usage_interval,
            last_completed, next_due, completed_count,
            linked_entity_id, linked_entity_type,
            reminder_mins, notify_channel, job_config,
            active, created_at, updated_at
        )
        SELECT
            id, title, COALESCE(description, ''), COALESCE(category, 'general'),
            COALESCE(assigned_to, ''), created_by,
            COALESCE(recurrence_type, 'weekly'),
            COALESCE(recurrence_rule, '{}'::jsonb),
            time_of_day, duration_mins,
            usage_metric, usage_interval,
            last_completed, next_due, COALESCE(completed_count, 0),
            linked_entity_id, linked_entity_type,
            COALESCE(reminder_mins, 60), COALESCE(notify_channel, 'both'),
            '{}'::jsonb,
            COALESCE(active, true), created_at, updated_at
        FROM public.schedules
        ON CONFLICT (id) DO NOTHING;
    END IF;

    SELECT COUNT(*) INTO target_rows_after FROM app_schedules.schedules;
    inserted := target_rows_after - target_rows_before;

    RAISE NOTICE 'schedules: source=% before=% after=% inserted=% (job_config_present=%)',
        source_rows, target_rows_before, target_rows_after, inserted, has_job_config;

    IF target_rows_after < source_rows THEN
        RAISE EXCEPTION
            'schedules migration sanity check failed: source=% target=%',
            source_rows, target_rows_after;
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 2. schedule_completions (depends on schedules existing for the FK)
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
        WHERE table_schema = 'public' AND table_name = 'schedule_completions'
    ) THEN
        RAISE NOTICE 'schedule_completions: no public.schedule_completions — fresh install, skipping';
        RETURN;
    END IF;

    SELECT COUNT(*) INTO source_rows FROM public.schedule_completions;
    SELECT COUNT(*) INTO target_rows_before FROM app_schedules.schedule_completions;

    -- Only migrate completions whose schedule_id already exists in
    -- app_schedules.schedules (the FK enforces this anyway, but we
    -- want a clean partial migration story if some source schedules
    -- were dropped by hand).
    INSERT INTO app_schedules.schedule_completions (
        id, schedule_id, completed_at, completed_by, notes, usage_value
    )
    SELECT
        sc.id, sc.schedule_id, sc.completed_at,
        COALESCE(sc.completed_by, ''), COALESCE(sc.notes, ''),
        sc.usage_value
    FROM public.schedule_completions sc
    WHERE EXISTS (
        SELECT 1 FROM app_schedules.schedules s
        WHERE s.id = sc.schedule_id
    )
    ON CONFLICT (id) DO NOTHING;

    SELECT COUNT(*) INTO target_rows_after FROM app_schedules.schedule_completions;
    inserted := target_rows_after - target_rows_before;

    RAISE NOTICE 'schedule_completions: source=% before=% after=% inserted=%',
        source_rows, target_rows_before, target_rows_after, inserted;

    -- Sanity: target >= count of source completions whose schedule_id
    -- exists in the target schedules table (looser than schedules
    -- because we deliberately skip orphan completions).
    IF target_rows_after < (
        SELECT COUNT(*)
        FROM public.schedule_completions sc
        WHERE EXISTS (
            SELECT 1 FROM app_schedules.schedules s
            WHERE s.id = sc.schedule_id
        )
    ) THEN
        RAISE EXCEPTION
            'schedule_completions migration sanity check failed: target=%',
            target_rows_after;
    END IF;
END $$;

COMMIT;

-- =============================================================================
-- After this migration:
--   - app_schedules.schedules contains a copy of every row that was in
--     public.schedules.
--   - app_schedules.schedule_completions contains every completion
--     whose schedule exists in app_schedules.schedules.
--   - The public.* tables are UNTOUCHED.
--
-- Verify your data, then optionally drop the legacy tables:
--
--   psql -d skipperbot -c "
--     -- destructive: requires explicit acknowledgement
--     -- BEGIN;
--     -- DROP TABLE public.schedule_completions CASCADE;
--     -- DROP TABLE public.schedules CASCADE;
--     -- COMMIT;
--   "
-- =============================================================================
