-- =============================================================================
-- Folders app — 001_initial.sql
-- =============================================================================
-- Creates the app_folders schema and all three tables.
--
-- Squashed from two legacy migrations:
--   * 048 — initial folders + folder_items + folder_knowledge schema
--           with GIN/ivfflat indexes
--   * 058 — added folders.deleted_at + partial index for soft-delete
--
-- The folders.parent_folder_id self-FK and the folder_items.folder_id /
-- folder_knowledge.folder_id within-app FKs are preserved (within-app
-- FKs are fine; only cross-schema FKs are forbidden).
--
-- pgvector requirement: this migration assumes the `vector` extension
-- has already been installed in the database. The platform's standalone
-- deploy/docker-initdb/01-create-extensions.sql ensures this on fresh
-- Docker installs; native installs need `CREATE EXTENSION vector` once
-- as a superuser.
--
-- Idempotent. Re-running is a no-op.

BEGIN;

CREATE SCHEMA IF NOT EXISTS app_folders;
SET LOCAL search_path TO app_folders, public;

-- =============================================================================
-- folders — the folder hierarchy itself
-- =============================================================================

CREATE TABLE IF NOT EXISTS folders (
    id                  text NOT NULL,
    name                text NOT NULL,
    description         text NOT NULL DEFAULT ''::text,
    owner               text NOT NULL DEFAULT ''::text,
    parent_folder_id    text DEFAULT ''::text,
    related_entity_id   text NOT NULL DEFAULT ''::text,
    icon                text NOT NULL DEFAULT 'folder'::text,
    color               text NOT NULL DEFAULT ''::text,
    sort_order          integer NOT NULL DEFAULT 0,
    tags                text[] NOT NULL DEFAULT '{}'::text[],
    created_by          text NOT NULL DEFAULT ''::text,
    created_at          timestamp with time zone NOT NULL DEFAULT now(),
    updated_at          timestamp with time zone NOT NULL DEFAULT now(),
    -- Added in legacy migration 058
    deleted_at          timestamp with time zone
);

DO $$ BEGIN
    ALTER TABLE folders
        ADD CONSTRAINT folders_pkey PRIMARY KEY (id);
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;

-- Self-FK on parent_folder_id (within-app; preserved from legacy).
DO $$ BEGIN
    ALTER TABLE folders
        ADD CONSTRAINT folders_parent_folder_id_fkey
        FOREIGN KEY (parent_folder_id) REFERENCES folders(id) ON DELETE SET NULL;
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_folders_owner   ON folders (owner);
CREATE INDEX IF NOT EXISTS idx_folders_parent  ON folders (parent_folder_id)
    WHERE parent_folder_id <> ''::text;
CREATE INDEX IF NOT EXISTS idx_folders_related ON folders (related_entity_id)
    WHERE related_entity_id <> ''::text;
-- From legacy migration 058
CREATE INDEX IF NOT EXISTS idx_folders_deleted ON folders (deleted_at)
    WHERE deleted_at IS NOT NULL;


-- =============================================================================
-- folder_items — junction table
-- =============================================================================

CREATE TABLE IF NOT EXISTS folder_items (
    id           serial NOT NULL,
    folder_id    text NOT NULL,
    entity_id    text NOT NULL,
    entity_type  text NOT NULL DEFAULT ''::text,
    position     integer NOT NULL DEFAULT 0,
    added_by     text NOT NULL DEFAULT ''::text,
    added_at     timestamp with time zone NOT NULL DEFAULT now()
);

DO $$ BEGIN
    ALTER TABLE folder_items
        ADD CONSTRAINT folder_items_pkey PRIMARY KEY (id);
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE folder_items
        ADD CONSTRAINT folder_items_folder_id_fkey
        FOREIGN KEY (folder_id) REFERENCES folders(id) ON DELETE CASCADE;
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE folder_items
        ADD CONSTRAINT folder_items_folder_id_entity_id_key
        UNIQUE (folder_id, entity_id);
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_folder_items_folder ON folder_items (folder_id);
CREATE INDEX IF NOT EXISTS idx_folder_items_entity ON folder_items (entity_id);


-- =============================================================================
-- folder_knowledge — LLM facts + content embeddings
-- =============================================================================

CREATE TABLE IF NOT EXISTS folder_knowledge (
    id            text NOT NULL,
    folder_id     text NOT NULL,
    entity_id     text NOT NULL,
    chunk_type    text NOT NULL DEFAULT 'content'::text,
    text          text NOT NULL,
    tags          text[] NOT NULL DEFAULT '{}'::text[],
    embedding     public.vector(1536),
    source_title  text NOT NULL DEFAULT ''::text,
    content_hash  text NOT NULL DEFAULT ''::text,
    processed_at  timestamp with time zone NOT NULL DEFAULT now()
);

DO $$ BEGIN
    ALTER TABLE folder_knowledge
        ADD CONSTRAINT folder_knowledge_pkey PRIMARY KEY (id);
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE folder_knowledge
        ADD CONSTRAINT folder_knowledge_folder_id_fkey
        FOREIGN KEY (folder_id) REFERENCES folders(id) ON DELETE CASCADE;
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_fk_folder    ON folder_knowledge (folder_id);
CREATE INDEX IF NOT EXISTS idx_fk_entity    ON folder_knowledge (entity_id);
CREATE INDEX IF NOT EXISTS idx_fk_type      ON folder_knowledge (chunk_type);
CREATE INDEX IF NOT EXISTS idx_fk_embedding ON folder_knowledge
    USING ivfflat (embedding public.vector_cosine_ops)
    WITH (lists = 10);

COMMIT;
