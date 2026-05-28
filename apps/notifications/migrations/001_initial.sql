-- =============================================================================
-- Notifications app — 001_initial.sql
-- =============================================================================
-- Creates the app_notifications schema and the notifications table
-- (one row per delivered or pending notification).
--
-- The platform's app_platform/migrator.py invokes this with
-- search_path = app_notifications, public already set within its
-- transaction, so unqualified table names resolve into the
-- notifications app's schema. The CREATE SCHEMA + SET search_path +
-- BEGIN/COMMIT lines at the top are a defensive belt-and-suspenders so
-- this file also applies cleanly if run by hand:
--     psql -d skipperbot -f apps/notifications/migrations/001_initial.sql
--
-- The whole migration runs in a single transaction so search_path
-- changes stick for every statement, and a failure rolls back cleanly.
--
-- Idempotent. Re-running is a no-op.

BEGIN;

CREATE SCHEMA IF NOT EXISTS app_notifications;
SET LOCAL search_path TO app_notifications, public;

-- =============================================================================
-- notifications — one row per cross-app "tell the user X" event
-- =============================================================================

CREATE TABLE IF NOT EXISTS notifications (
    id           text NOT NULL,
    recipient    text NOT NULL,
    message      text NOT NULL,
    source_type  text NOT NULL DEFAULT ''::text,
    source_id    text NOT NULL DEFAULT ''::text,
    channel      text NOT NULL DEFAULT ''::text,
    delivered    boolean NOT NULL DEFAULT true,
    created_at   timestamp with time zone NOT NULL DEFAULT now()
);

DO $$ BEGIN
    ALTER TABLE notifications
        ADD CONSTRAINT notifications_pkey PRIMARY KEY (id);
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_notifications_recipient ON notifications (recipient);
CREATE INDEX IF NOT EXISTS idx_notifications_source_id ON notifications (source_id)
    WHERE source_id <> ''::text;

COMMIT;
