-- =============================================================================
-- Backups app — 001_initial.sql
-- =============================================================================
-- Creates the app_backups schema + the backups audit table + PK index.
-- Mirrors the live public.backups schema 1:1 — same columns, same defaults —
-- so 002_migrate_from_public.sql can do a straight column-for-column copy.
--
-- The platform's app_platform/migrator.py invokes this with
-- search_path = app_backups, public already set within its transaction.
-- The CREATE SCHEMA + SET search_path + BEGIN/COMMIT lines at the top
-- are a defensive belt-and-suspenders so this file also applies cleanly
-- if run by hand:
--     psql -d skipperbot -f apps/backups/migrations/001_initial.sql
--
-- The whole migration runs in a single transaction so search_path
-- changes stick for every statement, and a failure rolls back cleanly.
--
-- Idempotent. Re-running is a no-op.

BEGIN;

CREATE SCHEMA IF NOT EXISTS app_backups;
SET LOCAL search_path TO app_backups, public;

-- =============================================================================
-- backups — one audit row per backup attempt
-- =============================================================================

CREATE TABLE IF NOT EXISTS backups (
    id              text NOT NULL,
    job_id          text,
    started_at      timestamp with time zone NOT NULL DEFAULT now(),
    completed_at    timestamp with time zone,
    status          text NOT NULL DEFAULT 'running'::text,
    pg_dump_size    bigint,
    zip_size        bigint,
    network_path    text,
    files_created   jsonb NOT NULL DEFAULT '[]'::jsonb,
    table_counts    jsonb NOT NULL DEFAULT '{}'::jsonb,
    duration_secs   real,
    error           text DEFAULT ''::text,
    created_by      text DEFAULT 'system'::text
);

DO $$ BEGIN
    ALTER TABLE backups
        ADD CONSTRAINT backups_pkey PRIMARY KEY (id);
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;

COMMIT;
