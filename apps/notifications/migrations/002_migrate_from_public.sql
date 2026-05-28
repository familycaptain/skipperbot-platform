-- =============================================================================
-- Notifications app — 002_migrate_from_public.sql
-- =============================================================================
-- One-shot data migration: moves notifications rows from the legacy
-- public schema (pre-packaging Skipperbot) into the app_notifications
-- schema created by 001_initial.sql.
--
-- Idempotent:
--   - INSERT uses ON CONFLICT (id) DO NOTHING so re-running won't
--     duplicate or overwrite.
--   - Wrapped in a DO block that checks if the source
--     public.notifications exists. On a fresh install (no legacy data)
--     the block no-ops silently — there's nothing to migrate.
--
-- Does NOT drop the source table. After this migration completes and
-- you've verified your data is intact in app_notifications.notifications,
-- you may manually drop the legacy public.notifications (instructions
-- at the bottom of this file).
--
-- Runs in a single transaction so a failure (e.g. column mismatch)
-- rolls back the whole thing.

BEGIN;

SET LOCAL search_path TO app_notifications, public;

-- ---------------------------------------------------------------------------
-- notifications
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
        WHERE table_schema = 'public' AND table_name = 'notifications'
    ) THEN
        RAISE NOTICE 'notifications: no public.notifications — fresh install, skipping';
        RETURN;
    END IF;

    SELECT COUNT(*) INTO source_rows FROM public.notifications;
    SELECT COUNT(*) INTO target_rows_before FROM app_notifications.notifications;

    INSERT INTO app_notifications.notifications (
        id, recipient, message, source_type, source_id, channel,
        delivered, created_at
    )
    SELECT
        id,
        COALESCE(recipient, ''),
        message,
        COALESCE(source_type, ''),
        COALESCE(source_id, ''),
        COALESCE(channel, ''),
        delivered,
        created_at
    FROM public.notifications
    ON CONFLICT (id) DO NOTHING;

    SELECT COUNT(*) INTO target_rows_after FROM app_notifications.notifications;
    inserted := target_rows_after - target_rows_before;

    RAISE NOTICE 'notifications: source=% before=% after=% inserted=%',
        source_rows, target_rows_before, target_rows_after, inserted;

    IF target_rows_after < source_rows THEN
        RAISE EXCEPTION
            'notifications migration sanity check failed: source=% target=%',
            source_rows, target_rows_after;
    END IF;
END $$;

COMMIT;

-- =============================================================================
-- After this migration:
--   - app_notifications.notifications contains a copy of every row that
--     was in public.notifications.
--   - public.notifications is UNTOUCHED. It still holds the legacy rows.
--   - apps/notifications/data.py reads from app_notifications.* from now on.
--
-- Verify your data, then optionally drop the legacy table to reclaim
-- the row-count clarity:
--
--   psql -d skipperbot -c "
--     -- destructive: requires explicit acknowledgement
--     -- BEGIN;
--     -- DROP TABLE public.notifications CASCADE;
--     -- COMMIT;
--   "
--
-- We don't drop it here on purpose — Stage 1 cutover happens against a
-- copy of prod, so the user gets to confirm everything works before
-- losing the legacy rows.
-- =============================================================================
