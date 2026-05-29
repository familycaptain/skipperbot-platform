-- =============================================================================
-- Timeline app — 001_initial.sql
-- =============================================================================
-- Creates the app_timeline schema + three tables:
--   * timeline_posts       — one row per post (body in documents app)
--   * timeline_photos      — carousel attachments (FK to posts, ON DELETE CASCADE)
--   * timeline_tag_index   — denormalised tag → post_count
-- Plus 7 indexes spanning author, tags (GIN), created_at, source_app,
-- visibility, and the author+visibility composite for personal-feed
-- queries.
--
-- Mirrors the live app_timeline schema 1:1 so older installs whose
-- timeline data already moved to app_timeline through a previous
-- migration loop see a no-op when this runs.
--
-- Idempotent. Re-running is a no-op.

BEGIN;

CREATE SCHEMA IF NOT EXISTS app_timeline;
SET LOCAL search_path TO app_timeline, public;

-- =============================================================================
-- timeline_posts — one row per post
-- =============================================================================

CREATE TABLE IF NOT EXISTS timeline_posts (
    id                text NOT NULL,
    author_id         text NOT NULL DEFAULT ''::text,
    title             text NOT NULL DEFAULT ''::text,
    doc_id            text,                                  -- documents app FK (logical, no DB FK)
    tags              text[] NOT NULL DEFAULT '{}'::text[],
    source_app        text NOT NULL DEFAULT ''::text,
    source_entity_id  text NOT NULL DEFAULT ''::text,
    source_label      text NOT NULL DEFAULT ''::text,
    pinned            boolean NOT NULL DEFAULT false,
    visibility        text NOT NULL DEFAULT 'everyone'::text,
    created_at        timestamp with time zone NOT NULL DEFAULT now(),
    updated_at        timestamp with time zone NOT NULL DEFAULT now()
);

DO $$ BEGIN
    ALTER TABLE timeline_posts
        ADD CONSTRAINT timeline_posts_pkey PRIMARY KEY (id);
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_tp_author      ON timeline_posts (author_id);
CREATE INDEX IF NOT EXISTS idx_tp_created     ON timeline_posts (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tp_tags        ON timeline_posts USING gin (tags);
CREATE INDEX IF NOT EXISTS idx_tp_visibility  ON timeline_posts (visibility);
CREATE INDEX IF NOT EXISTS idx_tp_author_vis  ON timeline_posts (author_id, visibility);
CREATE INDEX IF NOT EXISTS idx_tp_source      ON timeline_posts (source_app)
    WHERE source_app <> ''::text;

-- =============================================================================
-- timeline_photos — carousel attachments (within-app FK is fine)
-- =============================================================================

CREATE TABLE IF NOT EXISTS timeline_photos (
    id          text NOT NULL,
    post_id     text NOT NULL,
    image_id    text NOT NULL,
    caption     text NOT NULL DEFAULT ''::text,
    sort_order  integer NOT NULL DEFAULT 0,
    created_at  timestamp with time zone NOT NULL DEFAULT now()
);

DO $$ BEGIN
    ALTER TABLE timeline_photos
        ADD CONSTRAINT timeline_photos_pkey PRIMARY KEY (id);
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE timeline_photos
        ADD CONSTRAINT timeline_photos_post_id_fkey
        FOREIGN KEY (post_id) REFERENCES timeline_posts(id) ON DELETE CASCADE;
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_tph_post ON timeline_photos (post_id);

-- =============================================================================
-- timeline_tag_index — denormalised counts
-- =============================================================================

CREATE TABLE IF NOT EXISTS timeline_tag_index (
    tag           text NOT NULL,
    post_count    integer NOT NULL DEFAULT 0,
    last_used_at  timestamp with time zone NOT NULL DEFAULT now()
);

DO $$ BEGIN
    ALTER TABLE timeline_tag_index
        ADD CONSTRAINT timeline_tag_index_pkey PRIMARY KEY (tag);
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;

COMMIT;
