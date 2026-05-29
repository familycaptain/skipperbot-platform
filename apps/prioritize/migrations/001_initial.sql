-- =============================================================================
-- Prioritize app — 001_initial.sql
-- =============================================================================
-- Creates the app_prioritize schema + the priority_focus table + 4 indexes
-- (PK on id, two UNIQUE composites, one btree).
--
-- Mirrors the live public.priority_focus schema 1:1 — same columns, same
-- defaults, same constraints — so 002_migrate_from_public.sql can do
-- a straight column-for-column copy.
--
-- The platform's app_platform/migrator.py invokes this with
-- search_path = app_prioritize, public already set within its
-- transaction. The CREATE SCHEMA + SET search_path + BEGIN/COMMIT
-- lines at the top are a defensive belt-and-suspenders so this file
-- also applies cleanly if run by hand:
--     psql -d skipperbot -f apps/prioritize/migrations/001_initial.sql
--
-- The whole migration runs in a single transaction so search_path
-- changes stick for every statement, and a failure rolls back cleanly.
--
-- Idempotent. Re-running is a no-op.

BEGIN;

CREATE SCHEMA IF NOT EXISTS app_prioritize;
SET LOCAL search_path TO app_prioritize, public;

-- =============================================================================
-- priority_focus — per-user pinned items (max 3 active slots)
-- =============================================================================

CREATE TABLE IF NOT EXISTS priority_focus (
    id            text NOT NULL,
    user_id       text NOT NULL,
    slot_number   integer NOT NULL,
    source_type   text NOT NULL,
    source_id     text NOT NULL,
    created_at    timestamp with time zone NOT NULL DEFAULT now()
);

DO $$ BEGIN
    ALTER TABLE priority_focus
        ADD CONSTRAINT priority_focus_pkey PRIMARY KEY (id);
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE priority_focus
        ADD CONSTRAINT priority_focus_user_id_slot_number_key
        UNIQUE (user_id, slot_number);
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE priority_focus
        ADD CONSTRAINT priority_focus_user_id_source_id_key
        UNIQUE (user_id, source_id);
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_priority_focus_user ON priority_focus (user_id);

COMMIT;
