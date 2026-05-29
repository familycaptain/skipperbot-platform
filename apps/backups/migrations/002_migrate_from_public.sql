-- =============================================================================
-- Backups app — 002_migrate_from_public.sql
-- =============================================================================
-- One-shot data migration: moves rows from the legacy public.backups
-- table into the app_backups schema created by 001_initial.sql.
--
-- Idempotent:
--   - INSERT uses ON CONFLICT (id) DO NOTHING so re-running won't
--     duplicate or overwrite.
--   - Wrapped in a DO block that checks if public.backups exists,
--     so fresh installs (which never had it) are no-ops.
--
-- Does NOT drop the source table.
--
-- Runs in a single transaction so a failure rolls back the whole thing.

BEGIN;

SET LOCAL search_path TO app_backups, public;

DO $$
DECLARE
    source_rows int := 0;
    target_rows_before int := 0;
    target_rows_after int := 0;
    inserted int := 0;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'backups'
    ) THEN
        RAISE NOTICE 'backups: no public.backups — fresh install, skipping';
        RETURN;
    END IF;

    SELECT COUNT(*) INTO source_rows        FROM public.backups;
    SELECT COUNT(*) INTO target_rows_before FROM app_backups.backups;

    INSERT INTO app_backups.backups (
        id, job_id, started_at, completed_at, status,
        pg_dump_size, zip_size, network_path,
        files_created, table_counts, duration_secs,
        error, created_by
    )
    SELECT
        id,
        job_id,
        started_at,
        completed_at,
        COALESCE(status, 'running'),
        pg_dump_size,
        zip_size,
        network_path,
        COALESCE(files_created, '[]'::jsonb),
        COALESCE(table_counts, '{}'::jsonb),
        duration_secs,
        COALESCE(error, ''),
        COALESCE(created_by, 'system')
    FROM public.backups
    ON CONFLICT (id) DO NOTHING;

    SELECT COUNT(*) INTO target_rows_after FROM app_backups.backups;
    inserted := target_rows_after - target_rows_before;

    RAISE NOTICE 'backups: source=% before=% after=% inserted=%',
        source_rows, target_rows_before, target_rows_after, inserted;

    IF target_rows_after < source_rows THEN
        RAISE EXCEPTION
            'backups migration sanity check failed: source=% target=%',
            source_rows, target_rows_after;
    END IF;
END $$;

COMMIT;

-- =============================================================================
-- After this migration:
--   - app_backups.backups contains a copy of every row that was in
--     public.backups.
--   - public.backups is UNTOUCHED.
--
-- Verify your data, then optionally drop the legacy table:
--
--   psql -d skipperbot -c "
--     -- destructive: requires explicit acknowledgement
--     -- BEGIN;
--     -- DROP TABLE public.backups CASCADE;
--     -- COMMIT;
--   "
-- =============================================================================
