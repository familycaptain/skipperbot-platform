-- =============================================================================
-- Behaviors app — 001_initial.sql
-- =============================================================================
-- Creates the app_behaviors schema + the single behaviors table + 3 btree
-- indexes (scope, created_by, enabled).
--
-- Mirrors the live public.behaviors schema 1:1 — same columns, same
-- defaults, same indexes — so the 002_migrate_from_public.sql can do
-- a straight column-for-column copy.
--
-- The platform's app_platform/migrator.py invokes this with
-- search_path = app_behaviors, public already set within its
-- transaction. The CREATE SCHEMA + SET search_path + BEGIN/COMMIT
-- lines at the top are a defensive belt-and-suspenders so this file
-- also applies cleanly if run by hand:
--     psql -d skipperbot -f apps/behaviors/migrations/001_initial.sql
--
-- The whole migration runs in a single transaction so search_path
-- changes stick for every statement, and a failure rolls back cleanly.
--
-- Idempotent. Re-running is a no-op.

BEGIN;

CREATE SCHEMA IF NOT EXISTS app_behaviors;
SET LOCAL search_path TO app_behaviors, public;

-- =============================================================================
-- behaviors — user-customizable if/then rules, injected into every chat turn
-- =============================================================================

CREATE TABLE IF NOT EXISTS behaviors (
    id                    text NOT NULL,
    trigger_description   text NOT NULL,
    action_description    text NOT NULL,
    scope                 text NOT NULL DEFAULT 'user'::text,
    enabled               boolean NOT NULL DEFAULT true,
    created_by            text NOT NULL DEFAULT ''::text,
    notes                 text NOT NULL DEFAULT ''::text,
    created_at            timestamp with time zone NOT NULL DEFAULT now(),
    updated_at            timestamp with time zone NOT NULL DEFAULT now()
);

DO $$ BEGIN
    ALTER TABLE behaviors
        ADD CONSTRAINT behaviors_pkey PRIMARY KEY (id);
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_behaviors_scope       ON behaviors (scope);
CREATE INDEX IF NOT EXISTS idx_behaviors_created_by  ON behaviors (created_by);
CREATE INDEX IF NOT EXISTS idx_behaviors_enabled     ON behaviors (enabled);

COMMIT;
