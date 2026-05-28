-- =============================================================================
-- Lists app — 002_migrate_from_public.sql
-- =============================================================================
-- One-shot data migration: moves lists/list_items rows from the legacy
-- public schema (pre-packaging Skipperbot) into the app_lists schema
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
-- you've verified your data is intact in app_lists.*, you may manually
-- drop the legacy public.lists / public.list_items (instructions at the
-- bottom of this file).
--
-- Runs in a single transaction so a failure (e.g. column mismatch)
-- rolls back the whole thing.

BEGIN;

SET LOCAL search_path TO app_lists, public;

-- ---------------------------------------------------------------------------
-- 1. lists
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
        WHERE table_schema = 'public' AND table_name = 'lists'
    ) THEN
        RAISE NOTICE 'lists: no public.lists — fresh install, skipping';
        RETURN;
    END IF;

    SELECT COUNT(*) INTO source_rows FROM public.lists;
    SELECT COUNT(*) INTO target_rows_before FROM app_lists.lists;

    INSERT INTO app_lists.lists (
        id, name, aliases, trello, created_by, created_at
    )
    SELECT
        id, name,
        COALESCE(aliases, '{}'::text[]),
        trello,
        COALESCE(created_by, ''),
        created_at
    FROM public.lists
    ON CONFLICT (id) DO NOTHING;

    SELECT COUNT(*) INTO target_rows_after FROM app_lists.lists;
    inserted := target_rows_after - target_rows_before;

    RAISE NOTICE 'lists: source=% before=% after=% inserted=%',
        source_rows, target_rows_before, target_rows_after, inserted;

    -- Sanity: every source row should now exist in target (either pre-existed
    -- or was just inserted). Equivalently, target_rows_after >= source_rows.
    IF target_rows_after < source_rows THEN
        RAISE EXCEPTION
            'lists migration sanity check failed: source=% target=%',
            source_rows, target_rows_after;
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 2. list_items (depends on lists existing for the FK)
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    source_rows int := 0;
    target_rows_before int := 0;
    target_rows_after int := 0;
    inserted int := 0;
    has_archived_at boolean := false;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'list_items'
    ) THEN
        RAISE NOTICE 'list_items: no public.list_items — fresh install, skipping';
        RETURN;
    END IF;

    -- archived_at was added in migration 028; very old installs may not have it.
    SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name   = 'list_items'
          AND column_name  = 'archived_at'
    ) INTO has_archived_at;

    SELECT COUNT(*) INTO source_rows FROM public.list_items;
    SELECT COUNT(*) INTO target_rows_before FROM app_lists.list_items;

    IF has_archived_at THEN
        INSERT INTO app_lists.list_items (
            id, list_id, text, position, archived, archived_at,
            trello_card_id, added_by, added_at
        )
        SELECT
            id, list_id, text, position, archived, archived_at,
            COALESCE(trello_card_id, ''),
            COALESCE(added_by, ''),
            added_at
        FROM public.list_items
        ON CONFLICT (id) DO NOTHING;
    ELSE
        -- Legacy install without archived_at — back-fill NULL.
        INSERT INTO app_lists.list_items (
            id, list_id, text, position, archived, archived_at,
            trello_card_id, added_by, added_at
        )
        SELECT
            id, list_id, text, position, archived, NULL::timestamptz,
            COALESCE(trello_card_id, ''),
            COALESCE(added_by, ''),
            added_at
        FROM public.list_items
        ON CONFLICT (id) DO NOTHING;
    END IF;

    SELECT COUNT(*) INTO target_rows_after FROM app_lists.list_items;
    inserted := target_rows_after - target_rows_before;

    RAISE NOTICE 'list_items: source=% before=% after=% inserted=% (archived_at_present=%)',
        source_rows, target_rows_before, target_rows_after, inserted, has_archived_at;

    IF target_rows_after < source_rows THEN
        RAISE EXCEPTION
            'list_items migration sanity check failed: source=% target=%',
            source_rows, target_rows_after;
    END IF;
END $$;

COMMIT;

-- =============================================================================
-- After this migration:
--   - app_lists.lists / list_items contains a copy of every row that was
--     in public.lists / public.list_items.
--   - The public.* tables are UNTOUCHED. They still hold the legacy rows.
--   - apps/lists/data.py reads from app_lists.* from now on.
--
-- Verify your data, then optionally drop the legacy tables to reclaim
-- the row-count clarity:
--
--   psql -d skipperbot -c "
--     -- destructive: requires explicit acknowledgement
--     -- BEGIN;
--     -- DROP TABLE public.list_items CASCADE;  -- drops the FK first
--     -- DROP TABLE public.lists      CASCADE;
--     -- COMMIT;
--   "
--
-- We don't drop them here on purpose — Stage 1 cutover happens against a
-- copy of prod, so the user gets to confirm everything works before
-- losing the legacy rows.
-- =============================================================================
