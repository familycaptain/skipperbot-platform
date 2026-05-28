-- =============================================================================
-- Reminders app — 001_initial.sql
-- =============================================================================
-- Creates the app_reminders schema and the reminders table.
--
-- Squashed from three legacy migrations:
--   * 001_schema.sql    — base reminders columns + 2 indexes
--   * 018               — sort_order column
--   * 024               — schedule_id column (was REFERENCES schedules(id);
--                         in the packaged app it's a plain TEXT since apps
--                         don't cross-schema FK each other)
--
-- The platform's app_platform/migrator.py invokes this with
-- search_path = app_reminders, public already set within its
-- transaction. The CREATE SCHEMA + SET search_path + BEGIN/COMMIT
-- lines at the top are a defensive belt-and-suspenders so this file
-- also applies cleanly if run by hand:
--     psql -d skipperbot -f apps/reminders/migrations/001_initial.sql
--
-- The whole migration runs in a single transaction so search_path
-- changes stick for every statement, and a failure rolls back cleanly.
--
-- Idempotent. Re-running is a no-op.

BEGIN;

CREATE SCHEMA IF NOT EXISTS app_reminders;
SET LOCAL search_path TO app_reminders, public;

-- =============================================================================
-- reminders — per-user "tell me X at time Y"
-- =============================================================================

CREATE TABLE IF NOT EXISTS reminders (
    id            text NOT NULL,
    user_id       text NOT NULL,
    message       text NOT NULL,
    remind_at     timestamp with time zone NOT NULL,
    recurrence    text,                                      -- RFC-5545 RRULE string or NULL
    active        boolean NOT NULL DEFAULT true,
    nag           boolean NOT NULL DEFAULT false,
    last_nagged   text NOT NULL DEFAULT ''::text,            -- YYYY-MM-DD
    time_slot     text NOT NULL DEFAULT ''::text,            -- "morning"/"afternoon"/"evening"
    created_at    timestamp with time zone NOT NULL DEFAULT now(),
    sort_order    integer NOT NULL DEFAULT 0,
    schedule_id   text                                       -- references app_schedules.schedules.id (no FK)
);

DO $$ BEGIN
    ALTER TABLE reminders
        ADD CONSTRAINT reminders_pkey PRIMARY KEY (id);
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_reminders_user_id  ON reminders (user_id);
CREATE INDEX IF NOT EXISTS idx_reminders_active   ON reminders (active)
    WHERE active = true;
CREATE INDEX IF NOT EXISTS idx_reminders_schedule ON reminders (schedule_id)
    WHERE schedule_id IS NOT NULL;

COMMIT;
