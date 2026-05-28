-- =============================================================================
-- Schedules app — 001_initial.sql
-- =============================================================================
-- Creates the app_schedules schema and both schedule tables.
--
-- Squashed from three legacy migrations:
--   * 023 — base schema for schedules + schedule_completions
--   * 062 — added schedules.job_config (JSONB) so schedule-driven
--          jobs can carry per-occurrence parameters
--   * 065 — widened the recurrence_type CHECK to include 'rrule'
--          (the squashed initial already includes 'rrule' in the list)
--
-- The platform's app_platform/migrator.py invokes this with
-- search_path = app_schedules, public already set within its
-- transaction. The CREATE SCHEMA + SET search_path + BEGIN/COMMIT
-- lines at the top are a defensive belt-and-suspenders so this file
-- also applies cleanly if run by hand:
--     psql -d skipperbot -f apps/schedules/migrations/001_initial.sql
--
-- The whole migration runs in a single transaction so search_path
-- changes stick for every statement, and a failure rolls back cleanly.
--
-- Idempotent. Re-running is a no-op.

BEGIN;

CREATE SCHEMA IF NOT EXISTS app_schedules;
SET LOCAL search_path TO app_schedules, public;

-- =============================================================================
-- schedules — recurring events / chores / maintenance / school / auto / medical / general
-- =============================================================================

CREATE TABLE IF NOT EXISTS schedules (
    id                  text NOT NULL,
    title               text NOT NULL,
    description         text NOT NULL DEFAULT ''::text,
    category            text NOT NULL DEFAULT 'general'::text,
    assigned_to         text NOT NULL DEFAULT ''::text,
    created_by          text NOT NULL,

    -- Recurrence
    recurrence_type     text NOT NULL DEFAULT 'weekly'::text,
    recurrence_rule     jsonb NOT NULL DEFAULT '{}'::jsonb,
    time_of_day         time without time zone,
    duration_mins       integer,

    -- Usage-based (e.g. mileage)
    usage_metric        text,
    usage_interval      integer,

    -- Tracking
    last_completed      timestamp with time zone,
    next_due            timestamp with time zone,
    completed_count     integer NOT NULL DEFAULT 0,

    -- Links to other entities
    linked_entity_id    text,
    linked_entity_type  text,

    -- Notifications
    reminder_mins       integer NOT NULL DEFAULT 60,
    notify_channel      text NOT NULL DEFAULT 'both'::text,

    -- Job trigger payload (per-occurrence parameters when a schedule
    -- fires a job; from legacy migration 062)
    job_config          jsonb NOT NULL DEFAULT '{}'::jsonb,

    -- Status
    active              boolean NOT NULL DEFAULT true,
    created_at          timestamp with time zone NOT NULL DEFAULT now(),
    updated_at          timestamp with time zone NOT NULL DEFAULT now()
);

DO $$ BEGIN
    ALTER TABLE schedules
        ADD CONSTRAINT schedules_pkey PRIMARY KEY (id);
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE schedules
        ADD CONSTRAINT schedules_category_check CHECK (category = ANY (ARRAY[
            'chore'::text, 'maintenance'::text, 'school'::text,
            'auto'::text, 'medical'::text, 'general'::text
        ]));
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE schedules
        ADD CONSTRAINT schedules_recurrence_type_check CHECK (recurrence_type = ANY (ARRAY[
            'daily'::text, 'weekly'::text, 'monthly'::text, 'yearly'::text,
            'interval'::text, 'cron'::text, 'rrule'::text
        ]));
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE schedules
        ADD CONSTRAINT schedules_notify_channel_check CHECK (notify_channel = ANY (ARRAY[
            'app'::text, 'push'::text, 'both'::text, 'none'::text
        ]));
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_schedules_assigned ON schedules (assigned_to);
CREATE INDEX IF NOT EXISTS idx_schedules_category ON schedules (category);
CREATE INDEX IF NOT EXISTS idx_schedules_next_due ON schedules (next_due);
CREATE INDEX IF NOT EXISTS idx_schedules_active   ON schedules (active);
CREATE INDEX IF NOT EXISTS idx_schedules_linked   ON schedules (linked_entity_id)
    WHERE linked_entity_id IS NOT NULL;


-- =============================================================================
-- schedule_completions — one row per "Mark Done"
-- =============================================================================

CREATE TABLE IF NOT EXISTS schedule_completions (
    id            text NOT NULL,
    schedule_id   text NOT NULL,
    completed_at  timestamp with time zone NOT NULL DEFAULT now(),
    completed_by  text NOT NULL DEFAULT ''::text,
    notes         text NOT NULL DEFAULT ''::text,
    usage_value   integer
);

DO $$ BEGIN
    ALTER TABLE schedule_completions
        ADD CONSTRAINT schedule_completions_pkey PRIMARY KEY (id);
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE schedule_completions
        ADD CONSTRAINT schedule_completions_schedule_id_fkey
        FOREIGN KEY (schedule_id) REFERENCES schedules(id) ON DELETE CASCADE;
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_schedule_completions_schedule ON schedule_completions (schedule_id);
CREATE INDEX IF NOT EXISTS idx_schedule_completions_date     ON schedule_completions (completed_at DESC);

COMMIT;
