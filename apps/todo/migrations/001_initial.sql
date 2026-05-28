-- =============================================================================
-- Todo app — 001_initial.sql
-- =============================================================================
-- Creates the app_todo schema and the todo_config table (one row per user).
--
-- The platform's app_platform/migrator.py invokes this with
-- search_path = app_todo, public already set within its transaction,
-- so unqualified table names resolve into the todo app's schema. The
-- CREATE SCHEMA + SET search_path + BEGIN/COMMIT lines at the top are
-- a defensive belt-and-suspenders so this file also applies cleanly if
-- run by hand:
--     psql -d skipperbot -f apps/todo/migrations/001_initial.sql
--
-- The whole migration runs in a single transaction so search_path
-- changes stick for every statement, and a failure rolls back cleanly.
--
-- NOTE: ``default_list_id`` and ``backlog_list_id`` reference values in
-- ``app_lists.lists(id)`` but there is **no foreign key** — apps may not
-- cross-schema FK each other. Application-layer code (apps/todo/data.py
-- + apps/todo/store.py) is responsible for verifying that a referenced
-- list still exists before relying on it.
--
-- Idempotent. Re-running is a no-op.

BEGIN;

CREATE SCHEMA IF NOT EXISTS app_todo;
SET LOCAL search_path TO app_todo, public;

-- =============================================================================
-- todo_config — one row per user
-- =============================================================================

CREATE TABLE IF NOT EXISTS todo_config (
    user_id           text NOT NULL,
    default_list_id   text,                       -- references app_lists.lists.id (no FK)
    backlog_list_id   text,                       -- references app_lists.lists.id (no FK)
    nudge_enabled     boolean NOT NULL DEFAULT true,
    nudge_day         text NOT NULL DEFAULT 'saturday'::text,
    nudge_time        time NOT NULL DEFAULT '07:00'::time,
    show_on_calendar  boolean NOT NULL DEFAULT true,
    created_at        timestamp with time zone NOT NULL DEFAULT now(),
    updated_at        timestamp with time zone NOT NULL DEFAULT now()
);

DO $$ BEGIN
    ALTER TABLE todo_config
        ADD CONSTRAINT todo_config_pkey PRIMARY KEY (user_id);
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE todo_config
        ADD CONSTRAINT todo_config_nudge_day_check CHECK (nudge_day = ANY (ARRAY[
            'monday'::text, 'tuesday'::text, 'wednesday'::text, 'thursday'::text,
            'friday'::text, 'saturday'::text, 'sunday'::text
        ]));
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
END $$;

COMMIT;
