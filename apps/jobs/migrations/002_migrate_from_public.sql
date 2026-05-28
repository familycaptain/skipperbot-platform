-- =============================================================================
-- Jobs app — 002_migrate_from_public.sql
-- =============================================================================
-- One-shot data migration: moves jobs + job_logs rows from the legacy
-- public schema into the app_jobs schema created by 001_initial.sql.
--
-- Idempotent:
--   - INSERT uses ON CONFLICT (id) DO NOTHING so re-running won't
--     duplicate or overwrite.
--   - Wrapped in DO blocks that check if each source table exists.
--     On a fresh install (no legacy data) the blocks no-op silently.
--
-- Does NOT drop the source tables.
--
-- Runs in a single transaction so a failure rolls back the whole thing.

BEGIN;

SET LOCAL search_path TO app_jobs, public;

-- ---------------------------------------------------------------------------
-- 1. jobs
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    source_rows int := 0;
    target_rows_before int := 0;
    target_rows_after int := 0;
    inserted int := 0;
    has_progress_pct boolean := false;
    has_schedule_expr boolean := false;
    has_started_at boolean := false;
    has_completed_at boolean := false;
    has_claimed_by boolean := false;
    has_max_retries boolean := false;
    has_retry_count boolean := false;
    has_parent_job_id boolean := false;
    has_error boolean := false;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'jobs'
    ) THEN
        RAISE NOTICE 'jobs: no public.jobs — fresh install, skipping';
        RETURN;
    END IF;

    -- Detect which post-009 columns exist (migration 009 added all of
    -- these at once, so they're either all present or all absent).
    SELECT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema='public' AND table_name='jobs'
                     AND column_name='progress_pct')   INTO has_progress_pct;
    SELECT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema='public' AND table_name='jobs'
                     AND column_name='schedule_expr')  INTO has_schedule_expr;
    SELECT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema='public' AND table_name='jobs'
                     AND column_name='started_at')    INTO has_started_at;
    SELECT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema='public' AND table_name='jobs'
                     AND column_name='completed_at')  INTO has_completed_at;
    SELECT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema='public' AND table_name='jobs'
                     AND column_name='claimed_by')    INTO has_claimed_by;
    SELECT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema='public' AND table_name='jobs'
                     AND column_name='max_retries')   INTO has_max_retries;
    SELECT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema='public' AND table_name='jobs'
                     AND column_name='retry_count')   INTO has_retry_count;
    SELECT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema='public' AND table_name='jobs'
                     AND column_name='parent_job_id') INTO has_parent_job_id;
    SELECT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema='public' AND table_name='jobs'
                     AND column_name='error')         INTO has_error;

    SELECT COUNT(*) INTO source_rows FROM public.jobs;
    SELECT COUNT(*) INTO target_rows_before FROM app_jobs.jobs;

    -- Build a single INSERT that uses dynamic SQL to handle the
    -- "has these columns?" matrix. Easier than 256 IF-branches.
    --
    -- Required columns (present in every legacy install): id, name,
    -- job_type, command, description, scheduled_for, notify_user,
    -- status, created_by, created_at, last_run_at, last_result,
    -- run_count, progress, cancelled, config, output.
    --
    -- Post-009 columns are COALESCE'd with sane defaults when missing.
    EXECUTE format(
        $f$
        INSERT INTO app_jobs.jobs (
            id, name, job_type, command, description,
            scheduled_for, notify_user, status, created_by,
            created_at, last_run_at, last_result, run_count,
            progress, cancelled, config, output,
            progress_pct, schedule_expr, started_at, completed_at,
            claimed_by, max_retries, retry_count, parent_job_id, error
        )
        SELECT
            id, name, COALESCE(job_type, 'shell'), COALESCE(command, ''),
            COALESCE(description, ''),
            COALESCE(scheduled_for, ''), COALESCE(notify_user, ''),
            COALESCE(status, 'active'), COALESCE(created_by, ''),
            created_at, last_run_at, COALESCE(last_result, ''),
            COALESCE(run_count, 0),
            COALESCE(progress, ''), COALESCE(cancelled, false),
            COALESCE(config, '{}'::jsonb), COALESCE(output, '{}'::jsonb),
            %s,  -- progress_pct
            %s,  -- schedule_expr
            %s,  -- started_at
            %s,  -- completed_at
            %s,  -- claimed_by
            %s,  -- max_retries
            %s,  -- retry_count
            %s,  -- parent_job_id
            %s   -- error
        FROM public.jobs
        ON CONFLICT (id) DO NOTHING
        $f$,
        CASE WHEN has_progress_pct  THEN 'COALESCE(progress_pct, 0)'  ELSE '0' END,
        CASE WHEN has_schedule_expr THEN 'COALESCE(schedule_expr, ''{}''::jsonb)' ELSE '''{}''::jsonb' END,
        CASE WHEN has_started_at    THEN 'started_at'                 ELSE 'NULL::timestamptz' END,
        CASE WHEN has_completed_at  THEN 'completed_at'               ELSE 'NULL::timestamptz' END,
        CASE WHEN has_claimed_by    THEN 'COALESCE(claimed_by, '''')' ELSE '''''' END,
        CASE WHEN has_max_retries   THEN 'COALESCE(max_retries, 0)'   ELSE '0' END,
        CASE WHEN has_retry_count   THEN 'COALESCE(retry_count, 0)'   ELSE '0' END,
        CASE WHEN has_parent_job_id THEN 'COALESCE(parent_job_id, '''')' ELSE '''''' END,
        CASE WHEN has_error         THEN 'COALESCE(error, '''')'      ELSE '''''' END
    );

    SELECT COUNT(*) INTO target_rows_after FROM app_jobs.jobs;
    inserted := target_rows_after - target_rows_before;

    RAISE NOTICE 'jobs: source=% before=% after=% inserted=% (post-009-columns=%)',
        source_rows, target_rows_before, target_rows_after, inserted,
        has_progress_pct;

    IF target_rows_after < source_rows THEN
        RAISE EXCEPTION
            'jobs migration sanity check failed: source=% target=%',
            source_rows, target_rows_after;
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 2. job_logs (depends on jobs being present)
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
        WHERE table_schema = 'public' AND table_name = 'job_logs'
    ) THEN
        RAISE NOTICE 'job_logs: no public.job_logs — fresh install, skipping';
        RETURN;
    END IF;

    SELECT COUNT(*) INTO source_rows FROM public.job_logs;
    SELECT COUNT(*) INTO target_rows_before FROM app_jobs.job_logs;

    -- BIGSERIAL ids — we can't ON CONFLICT (id) DO NOTHING easily
    -- because the sequence will collide. Use ON CONFLICT (id) DO NOTHING
    -- and then advance the sequence to MAX(id)+1.
    INSERT INTO app_jobs.job_logs (id, job_id, created_at, level, message)
    SELECT
        id, job_id, created_at,
        COALESCE(level, 'INFO'), COALESCE(message, '')
    FROM public.job_logs
    ON CONFLICT (id) DO NOTHING;

    -- Bump the bigserial sequence past whatever id we just inserted.
    PERFORM setval(
        pg_get_serial_sequence('app_jobs.job_logs', 'id'),
        GREATEST(
            (SELECT COALESCE(MAX(id), 0) FROM app_jobs.job_logs),
            1
        )
    );

    SELECT COUNT(*) INTO target_rows_after FROM app_jobs.job_logs;
    inserted := target_rows_after - target_rows_before;

    RAISE NOTICE 'job_logs: source=% before=% after=% inserted=%',
        source_rows, target_rows_before, target_rows_after, inserted;

    IF target_rows_after < source_rows THEN
        RAISE EXCEPTION
            'job_logs migration sanity check failed: source=% target=%',
            source_rows, target_rows_after;
    END IF;
END $$;

COMMIT;

-- =============================================================================
-- After this migration:
--   - app_jobs.jobs contains a copy of every row that was in public.jobs.
--   - app_jobs.job_logs contains a copy of every public.job_logs row.
--   - The public.* tables are UNTOUCHED.
--   - apps/jobs/data.py reads from app_jobs.* from now on.
--
-- Verify your data, then optionally drop the legacy tables:
--
--   psql -d skipperbot -c "
--     -- destructive: requires explicit acknowledgement
--     -- BEGIN;
--     -- DROP TABLE public.job_logs CASCADE;
--     -- DROP TABLE public.jobs CASCADE;
--     -- COMMIT;
--   "
-- =============================================================================
