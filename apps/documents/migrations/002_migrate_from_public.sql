-- =============================================================================
-- Documents app — 002_migrate_from_public.sql
-- =============================================================================
-- One-shot data migration: moves documents rows from the legacy public
-- schema into the app_documents schema created by 001_initial.sql.
--
-- Idempotent:
--   - INSERT uses ON CONFLICT (id) DO NOTHING so re-running won't
--     duplicate or overwrite.
--   - Wrapped in a DO block that checks if public.documents exists.
--     On a fresh install (no legacy data) the block no-ops silently.
--
-- Handles legacy installs that pre-date the embedding column
-- (migration 061) — embedding is COALESCE'd to NULL when missing.
--
-- Does NOT drop the source table.

BEGIN;

SET LOCAL search_path TO app_documents, public;

-- ---------------------------------------------------------------------------
-- documents
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    source_rows int := 0;
    target_rows_before int := 0;
    target_rows_after int := 0;
    inserted int := 0;
    has_embedding boolean := false;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'documents'
    ) THEN
        RAISE NOTICE 'documents: no public.documents — fresh install, skipping';
        RETURN;
    END IF;

    SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'documents'
          AND column_name  = 'embedding'
    ) INTO has_embedding;

    SELECT COUNT(*) INTO source_rows FROM public.documents;
    SELECT COUNT(*) INTO target_rows_before FROM app_documents.documents;

    IF has_embedding THEN
        INSERT INTO app_documents.documents (
            id, title, content, tags, word_count,
            related_entity_id, parent_doc_id, version,
            created_by, created_at, updated_at, embedding
        )
        SELECT
            id, title, COALESCE(content, ''),
            COALESCE(tags, '{}'::text[]), COALESCE(word_count, 0),
            COALESCE(related_entity_id, ''), COALESCE(parent_doc_id, ''),
            COALESCE(version, 1), COALESCE(created_by, ''),
            created_at, updated_at, embedding
        FROM public.documents
        ON CONFLICT (id) DO NOTHING;
    ELSE
        -- Pre-061 install — embedding column does not exist; back-fill NULL.
        INSERT INTO app_documents.documents (
            id, title, content, tags, word_count,
            related_entity_id, parent_doc_id, version,
            created_by, created_at, updated_at, embedding
        )
        SELECT
            id, title, COALESCE(content, ''),
            COALESCE(tags, '{}'::text[]), COALESCE(word_count, 0),
            COALESCE(related_entity_id, ''), COALESCE(parent_doc_id, ''),
            COALESCE(version, 1), COALESCE(created_by, ''),
            created_at, updated_at, NULL::public.vector
        FROM public.documents
        ON CONFLICT (id) DO NOTHING;
    END IF;

    SELECT COUNT(*) INTO target_rows_after FROM app_documents.documents;
    inserted := target_rows_after - target_rows_before;

    RAISE NOTICE 'documents: source=% before=% after=% inserted=% (embedding_present=%)',
        source_rows, target_rows_before, target_rows_after, inserted, has_embedding;

    IF target_rows_after < source_rows THEN
        RAISE EXCEPTION
            'documents migration sanity check failed: source=% target=%',
            source_rows, target_rows_after;
    END IF;
END $$;

COMMIT;

-- =============================================================================
-- After this migration:
--   - app_documents.documents contains a copy of every row that was
--     in public.documents (including embeddings if the source had them).
--   - public.documents is UNTOUCHED.
--
-- Verify your data, then optionally drop the legacy table:
--
--   psql -d skipperbot -c "
--     -- destructive: requires explicit acknowledgement
--     -- BEGIN;
--     -- DROP TABLE public.documents CASCADE;
--     -- COMMIT;
--   "
-- =============================================================================
