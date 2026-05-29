-- =============================================================================
-- Documents app — 001_initial.sql
-- =============================================================================
-- Creates the app_documents schema and the documents table.
--
-- Squashed from two legacy migrations:
--   * 001 — base schema + GIN index on tags
--   * 061 — added embedding vector(1536) column + ivfflat index
--           for semantic search
--
-- pgvector requirement: this migration assumes the `vector` extension
-- has already been installed in the database. The platform's standalone
-- deploy/docker-initdb/01-create-extensions.sql ensures this on fresh
-- Docker installs; native installs need to install pgvector once and
-- `CREATE EXTENSION vector;` manually as a superuser.
--
-- The platform's app_platform/migrator.py invokes this with
-- search_path = app_documents, public already set within its
-- transaction. The CREATE SCHEMA + SET search_path + BEGIN/COMMIT
-- lines at the top are a defensive belt-and-suspenders so this file
-- also applies cleanly if run by hand.
--
-- The whole migration runs in a single transaction so search_path
-- changes stick for every statement, and a failure rolls back cleanly.
--
-- Idempotent. Re-running is a no-op.

BEGIN;

CREATE SCHEMA IF NOT EXISTS app_documents;
SET LOCAL search_path TO app_documents, public;

-- =============================================================================
-- documents — markdown documents with semantic search
-- =============================================================================

CREATE TABLE IF NOT EXISTS documents (
    id                  text NOT NULL,
    title               text NOT NULL,
    content             text NOT NULL DEFAULT ''::text,
    tags                text[] NOT NULL DEFAULT '{}'::text[],
    word_count          integer NOT NULL DEFAULT 0,
    related_entity_id   text NOT NULL DEFAULT ''::text,
    parent_doc_id       text NOT NULL DEFAULT ''::text,
    version             integer NOT NULL DEFAULT 1,
    created_by          text NOT NULL DEFAULT ''::text,
    created_at          timestamp with time zone NOT NULL DEFAULT now(),
    updated_at          timestamp with time zone NOT NULL DEFAULT now(),
    embedding           public.vector(1536)
);

DO $$ BEGIN
    ALTER TABLE documents
        ADD CONSTRAINT documents_pkey PRIMARY KEY (id);
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;

-- GIN index for fast tag filtering (added in legacy migration 001)
CREATE INDEX IF NOT EXISTS idx_documents_tags
    ON documents USING gin (tags);

-- ivfflat index for semantic search (added in legacy migration 061).
-- 1536-dim cosine distance with 10 lists.
CREATE INDEX IF NOT EXISTS idx_documents_embedding
    ON documents USING ivfflat (embedding public.vector_cosine_ops)
    WITH (lists = 10);

COMMIT;
