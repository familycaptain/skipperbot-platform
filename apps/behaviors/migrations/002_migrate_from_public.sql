-- =============================================================================
-- Behaviors app — 002_migrate_from_public.sql
-- =============================================================================
-- One-shot data migration: moves rows from the legacy public.behaviors
-- table into the app_behaviors schema created by 001_initial.sql.
--
-- Idempotent:
--   - INSERT uses ON CONFLICT (id) DO NOTHING so re-running won't
--     duplicate or overwrite.
--   - Wrapped in a DO block that checks if public.behaviors exists,
--     so fresh installs (which never had it) are no-ops.
--
-- Does NOT drop the source table.
--
-- Runs in a single transaction so a failure rolls back the whole thing.

BEGIN;

SET LOCAL search_path TO app_behaviors, public;

DO $$
DECLARE
    source_rows int := 0;
    target_rows_before int := 0;
    target_rows_after int := 0;
    inserted int := 0;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'behaviors'
    ) THEN
        RAISE NOTICE 'behaviors: no public.behaviors — fresh install, skipping';
        RETURN;
    END IF;

    SELECT COUNT(*) INTO source_rows         FROM public.behaviors;
    SELECT COUNT(*) INTO target_rows_before  FROM app_behaviors.behaviors;

    INSERT INTO app_behaviors.behaviors (
        id, trigger_description, action_description, scope,
        enabled, created_by, notes, created_at, updated_at
    )
    SELECT
        id,
        COALESCE(trigger_description, ''),
        COALESCE(action_description, ''),
        COALESCE(scope, 'user'),
        COALESCE(enabled, TRUE),
        COALESCE(created_by, ''),
        COALESCE(notes, ''),
        created_at,
        updated_at
    FROM public.behaviors
    ON CONFLICT (id) DO NOTHING;

    SELECT COUNT(*) INTO target_rows_after FROM app_behaviors.behaviors;
    inserted := target_rows_after - target_rows_before;

    RAISE NOTICE 'behaviors: source=% before=% after=% inserted=%',
        source_rows, target_rows_before, target_rows_after, inserted;

    IF target_rows_after < source_rows THEN
        RAISE EXCEPTION
            'behaviors migration sanity check failed: source=% target=%',
            source_rows, target_rows_after;
    END IF;
END $$;

COMMIT;

-- =============================================================================
-- After this migration:
--   - app_behaviors.behaviors contains a copy of every row that was in
--     public.behaviors.
--   - public.behaviors is UNTOUCHED.
--
-- Verify your data, then optionally drop the legacy table:
--
--   psql -d skipperbot -c "
--     -- destructive: requires explicit acknowledgement
--     -- BEGIN;
--     -- DROP TABLE public.behaviors CASCADE;
--     -- COMMIT;
--   "
-- =============================================================================
