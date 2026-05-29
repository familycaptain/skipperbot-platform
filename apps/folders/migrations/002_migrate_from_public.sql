-- =============================================================================
-- Folders app — 002_migrate_from_public.sql
-- =============================================================================
-- One-shot data migration: moves folders / folder_items / folder_knowledge
-- rows from the legacy public schema into the app_folders schema created
-- by 001_initial.sql.
--
-- Idempotent:
--   - INSERTs use ON CONFLICT (id) DO NOTHING (folders + knowledge) and
--     ON CONFLICT (folder_id, entity_id) DO NOTHING (items) so re-running
--     won't duplicate or overwrite.
--   - Wrapped in DO blocks that check if each source table exists.
--   - Handles legacy installs that pre-date the soft-delete column
--     (migration 058 — deleted_at was added).
--
-- Does NOT drop the source tables.
--
-- Runs in a single transaction so a failure rolls back the whole thing.

BEGIN;

SET LOCAL search_path TO app_folders, public;

-- ---------------------------------------------------------------------------
-- 1. folders
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    source_rows int := 0;
    target_rows_before int := 0;
    target_rows_after int := 0;
    inserted int := 0;
    has_deleted_at boolean := false;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'folders'
    ) THEN
        RAISE NOTICE 'folders: no public.folders — fresh install, skipping';
        RETURN;
    END IF;

    -- deleted_at was added in legacy migration 058.
    SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'folders'
          AND column_name  = 'deleted_at'
    ) INTO has_deleted_at;

    SELECT COUNT(*) INTO source_rows FROM public.folders;
    SELECT COUNT(*) INTO target_rows_before FROM app_folders.folders;

    IF has_deleted_at THEN
        INSERT INTO app_folders.folders (
            id, name, description, owner, parent_folder_id,
            related_entity_id, icon, color, sort_order, tags,
            created_by, created_at, updated_at, deleted_at
        )
        SELECT
            id, name, COALESCE(description, ''),
            COALESCE(owner, ''),
            parent_folder_id,  -- nullable, preserve as-is
            COALESCE(related_entity_id, ''),
            COALESCE(icon, 'folder'), COALESCE(color, ''),
            COALESCE(sort_order, 0), COALESCE(tags, '{}'::text[]),
            COALESCE(created_by, ''), created_at, updated_at, deleted_at
        FROM public.folders
        ON CONFLICT (id) DO NOTHING;
    ELSE
        -- Pre-058 install — back-fill deleted_at = NULL.
        INSERT INTO app_folders.folders (
            id, name, description, owner, parent_folder_id,
            related_entity_id, icon, color, sort_order, tags,
            created_by, created_at, updated_at, deleted_at
        )
        SELECT
            id, name, COALESCE(description, ''),
            COALESCE(owner, ''),
            parent_folder_id,
            COALESCE(related_entity_id, ''),
            COALESCE(icon, 'folder'), COALESCE(color, ''),
            COALESCE(sort_order, 0), COALESCE(tags, '{}'::text[]),
            COALESCE(created_by, ''), created_at, updated_at, NULL::timestamptz
        FROM public.folders
        ON CONFLICT (id) DO NOTHING;
    END IF;

    SELECT COUNT(*) INTO target_rows_after FROM app_folders.folders;
    inserted := target_rows_after - target_rows_before;

    RAISE NOTICE 'folders: source=% before=% after=% inserted=% (deleted_at_present=%)',
        source_rows, target_rows_before, target_rows_after, inserted, has_deleted_at;

    IF target_rows_after < source_rows THEN
        RAISE EXCEPTION
            'folders migration sanity check failed: source=% target=%',
            source_rows, target_rows_after;
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 2. folder_items (depends on folders for the FK)
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
        WHERE table_schema = 'public' AND table_name = 'folder_items'
    ) THEN
        RAISE NOTICE 'folder_items: no public.folder_items — fresh install, skipping';
        RETURN;
    END IF;

    SELECT COUNT(*) INTO source_rows FROM public.folder_items;
    SELECT COUNT(*) INTO target_rows_before FROM app_folders.folder_items;

    -- Only migrate items whose folder_id exists in the target table
    -- (the FK enforces this; partial-migration tolerance).
    INSERT INTO app_folders.folder_items (
        folder_id, entity_id, entity_type, position, added_by, added_at
    )
    SELECT
        fi.folder_id, fi.entity_id,
        COALESCE(fi.entity_type, ''),
        COALESCE(fi.position, 0),
        COALESCE(fi.added_by, ''),
        fi.added_at
    FROM public.folder_items fi
    WHERE EXISTS (
        SELECT 1 FROM app_folders.folders f WHERE f.id = fi.folder_id
    )
    ON CONFLICT (folder_id, entity_id) DO NOTHING;

    -- Bump the bigserial sequence past whatever ids we inserted
    PERFORM setval(
        pg_get_serial_sequence('app_folders.folder_items', 'id'),
        GREATEST(
            (SELECT COALESCE(MAX(id), 0) FROM app_folders.folder_items),
            1
        )
    );

    SELECT COUNT(*) INTO target_rows_after FROM app_folders.folder_items;
    inserted := target_rows_after - target_rows_before;

    RAISE NOTICE 'folder_items: source=% before=% after=% inserted=%',
        source_rows, target_rows_before, target_rows_after, inserted;
END $$;

-- ---------------------------------------------------------------------------
-- 3. folder_knowledge (depends on folders for the FK)
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
        WHERE table_schema = 'public' AND table_name = 'folder_knowledge'
    ) THEN
        RAISE NOTICE 'folder_knowledge: no public.folder_knowledge — fresh install, skipping';
        RETURN;
    END IF;

    SELECT COUNT(*) INTO source_rows FROM public.folder_knowledge;
    SELECT COUNT(*) INTO target_rows_before FROM app_folders.folder_knowledge;

    INSERT INTO app_folders.folder_knowledge (
        id, folder_id, entity_id, chunk_type, text, tags,
        embedding, source_title, content_hash, processed_at
    )
    SELECT
        fk.id, fk.folder_id, fk.entity_id,
        COALESCE(fk.chunk_type, 'content'),
        fk.text, COALESCE(fk.tags, '{}'::text[]),
        fk.embedding,
        COALESCE(fk.source_title, ''),
        COALESCE(fk.content_hash, ''),
        fk.processed_at
    FROM public.folder_knowledge fk
    WHERE EXISTS (
        SELECT 1 FROM app_folders.folders f WHERE f.id = fk.folder_id
    )
    ON CONFLICT (id) DO NOTHING;

    SELECT COUNT(*) INTO target_rows_after FROM app_folders.folder_knowledge;
    inserted := target_rows_after - target_rows_before;

    RAISE NOTICE 'folder_knowledge: source=% before=% after=% inserted=%',
        source_rows, target_rows_before, target_rows_after, inserted;
END $$;

COMMIT;

-- =============================================================================
-- After this migration:
--   - app_folders.folders / folder_items / folder_knowledge contain a
--     copy of every row that was in public.*.
--   - public.* tables are UNTOUCHED.
--
-- Verify your data, then optionally drop the legacy tables:
--
--   psql -d skipperbot -c "
--     -- destructive: requires explicit acknowledgement
--     -- BEGIN;
--     -- DROP TABLE public.folder_knowledge CASCADE;
--     -- DROP TABLE public.folder_items CASCADE;
--     -- DROP TABLE public.folders CASCADE;
--     -- COMMIT;
--   "
-- =============================================================================
