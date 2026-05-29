-- =============================================================================
-- Prioritize app — 002_migrate_from_public.sql
-- =============================================================================
-- One-shot data migration: moves rows from the legacy public.priority_focus
-- table into the app_prioritize schema created by 001_initial.sql.
--
-- Idempotent:
--   - INSERT uses ON CONFLICT (id) DO NOTHING so re-running won't
--     duplicate or overwrite.
--   - Wrapped in a DO block that checks if public.priority_focus
--     exists, so fresh installs (which never had it) are no-ops.
--
-- Does NOT drop the source table.
--
-- Runs in a single transaction so a failure rolls back the whole thing.

BEGIN;

SET LOCAL search_path TO app_prioritize, public;

DO $$
DECLARE
    source_rows int := 0;
    target_rows_before int := 0;
    target_rows_after int := 0;
    inserted int := 0;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'priority_focus'
    ) THEN
        RAISE NOTICE 'priority_focus: no public.priority_focus — fresh install, skipping';
        RETURN;
    END IF;

    SELECT COUNT(*) INTO source_rows        FROM public.priority_focus;
    SELECT COUNT(*) INTO target_rows_before FROM app_prioritize.priority_focus;

    INSERT INTO app_prioritize.priority_focus (
        id, user_id, slot_number, source_type, source_id, created_at
    )
    SELECT
        id, user_id, slot_number, source_type, source_id, created_at
    FROM public.priority_focus
    ON CONFLICT (id) DO NOTHING;

    SELECT COUNT(*) INTO target_rows_after FROM app_prioritize.priority_focus;
    inserted := target_rows_after - target_rows_before;

    RAISE NOTICE 'priority_focus: source=% before=% after=% inserted=%',
        source_rows, target_rows_before, target_rows_after, inserted;

    IF target_rows_after < source_rows THEN
        RAISE EXCEPTION
            'priority_focus migration sanity check failed: source=% target=%',
            source_rows, target_rows_after;
    END IF;
END $$;

COMMIT;

-- =============================================================================
-- After this migration:
--   - app_prioritize.priority_focus contains a copy of every row that was in
--     public.priority_focus.
--   - public.priority_focus is UNTOUCHED.
--
-- Verify your data, then optionally drop the legacy table:
--
--   psql -d skipperbot -c "
--     -- destructive: requires explicit acknowledgement
--     -- BEGIN;
--     -- DROP TABLE public.priority_focus CASCADE;
--     -- COMMIT;
--   "
-- =============================================================================
