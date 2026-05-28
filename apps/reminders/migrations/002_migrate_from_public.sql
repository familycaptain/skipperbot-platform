-- =============================================================================
-- Reminders app — 002_migrate_from_public.sql
-- =============================================================================
-- One-shot data migration: moves reminders rows from the legacy public
-- schema (pre-packaging Skipperbot) into the app_reminders schema
-- created by 001_initial.sql.
--
-- Idempotent:
--   - INSERT uses ON CONFLICT (id) DO NOTHING so re-running won't
--     duplicate or overwrite.
--   - Wrapped in a DO block that checks if the source public.reminders
--     exists. On a fresh install (no legacy data) the block no-ops
--     silently — there's nothing to migrate.
--
-- Does NOT drop the source table. After this migration completes and
-- you've verified your data is intact in app_reminders.reminders, you
-- may manually drop the legacy public.reminders (instructions at the
-- bottom of this file).
--
-- Runs in a single transaction so a failure (e.g. column mismatch)
-- rolls back the whole thing.

BEGIN;

SET LOCAL search_path TO app_reminders, public;

-- ---------------------------------------------------------------------------
-- reminders
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    source_rows int := 0;
    target_rows_before int := 0;
    target_rows_after int := 0;
    inserted int := 0;
    has_sort_order boolean := false;
    has_schedule_id boolean := false;
BEGIN
    -- Skip silently if there's nothing to migrate (fresh install case).
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'reminders'
    ) THEN
        RAISE NOTICE 'reminders: no public.reminders — fresh install, skipping';
        RETURN;
    END IF;

    -- sort_order was added in migration 018; schedule_id in migration 024.
    -- Very old installs may not have either yet.
    SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'reminders'
          AND column_name  = 'sort_order'
    ) INTO has_sort_order;

    SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'reminders'
          AND column_name  = 'schedule_id'
    ) INTO has_schedule_id;

    SELECT COUNT(*) INTO source_rows FROM public.reminders;
    SELECT COUNT(*) INTO target_rows_before FROM app_reminders.reminders;

    IF has_sort_order AND has_schedule_id THEN
        INSERT INTO app_reminders.reminders (
            id, user_id, message, remind_at, recurrence, active, nag,
            last_nagged, time_slot, created_at, sort_order, schedule_id
        )
        SELECT
            id, user_id, message, remind_at, recurrence, active, nag,
            COALESCE(last_nagged, ''), COALESCE(time_slot, ''),
            created_at, sort_order, schedule_id
        FROM public.reminders
        ON CONFLICT (id) DO NOTHING;
    ELSIF has_sort_order THEN
        INSERT INTO app_reminders.reminders (
            id, user_id, message, remind_at, recurrence, active, nag,
            last_nagged, time_slot, created_at, sort_order, schedule_id
        )
        SELECT
            id, user_id, message, remind_at, recurrence, active, nag,
            COALESCE(last_nagged, ''), COALESCE(time_slot, ''),
            created_at, sort_order, NULL::text
        FROM public.reminders
        ON CONFLICT (id) DO NOTHING;
    ELSE
        -- Legacy install without either column — back-fill defaults.
        INSERT INTO app_reminders.reminders (
            id, user_id, message, remind_at, recurrence, active, nag,
            last_nagged, time_slot, created_at, sort_order, schedule_id
        )
        SELECT
            id, user_id, message, remind_at, recurrence, active, nag,
            COALESCE(last_nagged, ''), COALESCE(time_slot, ''),
            created_at, 0, NULL::text
        FROM public.reminders
        ON CONFLICT (id) DO NOTHING;
    END IF;

    SELECT COUNT(*) INTO target_rows_after FROM app_reminders.reminders;
    inserted := target_rows_after - target_rows_before;

    RAISE NOTICE 'reminders: source=% before=% after=% inserted=% (sort_order_present=%, schedule_id_present=%)',
        source_rows, target_rows_before, target_rows_after, inserted, has_sort_order, has_schedule_id;

    IF target_rows_after < source_rows THEN
        RAISE EXCEPTION
            'reminders migration sanity check failed: source=% target=%',
            source_rows, target_rows_after;
    END IF;
END $$;

COMMIT;

-- =============================================================================
-- After this migration:
--   - app_reminders.reminders contains a copy of every row that was in
--     public.reminders.
--   - public.reminders is UNTOUCHED. It still holds the legacy rows.
--   - apps/reminders/data.py reads from app_reminders.* from now on.
--
-- Verify your data, then optionally drop the legacy table:
--
--   psql -d skipperbot -c "
--     -- destructive: requires explicit acknowledgement
--     -- BEGIN;
--     -- DROP TABLE public.reminders CASCADE;
--     -- COMMIT;
--   "
--
-- We don't drop it here on purpose — Stage 1 cutover happens against a
-- copy of prod, so the user gets to confirm everything works before
-- losing the legacy rows.
-- =============================================================================
