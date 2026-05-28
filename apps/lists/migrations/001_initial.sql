-- =============================================================================
-- Lists app — 001_initial.sql
-- =============================================================================
-- Creates the app_lists schema and the lists/list_items tables.
--
-- The platform's app_platform/migrator.py invokes this with
-- search_path = app_lists, public already set within its transaction,
-- so unqualified table names resolve into the lists app's schema. The
-- CREATE SCHEMA + SET search_path + BEGIN/COMMIT lines at the top are
-- a defensive belt-and-suspenders so this file also applies cleanly if
-- run by hand:
--     psql -d skipperbot -f apps/lists/migrations/001_initial.sql
--
-- The whole migration runs in a single transaction so search_path
-- changes stick for every statement, and a failure rolls back cleanly.
--
-- Idempotent. Re-running is a no-op.

BEGIN;

CREATE SCHEMA IF NOT EXISTS app_lists;
SET LOCAL search_path TO app_lists, public;

-- =============================================================================
-- lists — named ordered collections
-- =============================================================================

CREATE TABLE IF NOT EXISTS lists (
    id          text NOT NULL,
    name        text NOT NULL,
    aliases     text[] NOT NULL DEFAULT '{}'::text[],
    trello      jsonb,
    created_by  text NOT NULL DEFAULT ''::text,
    created_at  timestamp with time zone NOT NULL DEFAULT now()
);

DO $$ BEGIN
    ALTER TABLE lists
        ADD CONSTRAINT lists_pkey PRIMARY KEY (id);
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;


-- =============================================================================
-- list_items — items in a list, ordered by position
-- =============================================================================

CREATE TABLE IF NOT EXISTS list_items (
    id              text NOT NULL,
    list_id         text NOT NULL,
    text            text NOT NULL,
    position        integer NOT NULL DEFAULT 0,
    archived        boolean NOT NULL DEFAULT false,
    archived_at     timestamp with time zone,
    trello_card_id  text NOT NULL DEFAULT ''::text,
    added_by        text NOT NULL DEFAULT ''::text,
    added_at        timestamp with time zone NOT NULL DEFAULT now()
);

DO $$ BEGIN
    ALTER TABLE list_items
        ADD CONSTRAINT list_items_pkey PRIMARY KEY (id);
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE list_items
        ADD CONSTRAINT list_items_list_id_fkey
        FOREIGN KEY (list_id) REFERENCES lists(id) ON DELETE CASCADE;
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_list_items_list_id ON list_items (list_id);

COMMIT;
