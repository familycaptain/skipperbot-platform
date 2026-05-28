-- =============================================================================
-- Jobs app — 001_initial.sql
-- =============================================================================
-- Creates the app_jobs schema and both job tables.
--
-- Squashed from four legacy migrations:
--   * 001 — base `jobs` table + the original (restrictive) job_type CHECK
--   * 009 — relaxed job_type CHECK + added 9 columns (progress_pct,
--           schedule_expr, started_at, completed_at, claimed_by,
--           max_retries, retry_count, parent_job_id, error) + 3 indexes
--   * 010 — created the job_logs table + 2 indexes
--   * 063 — dropped the `schedule TEXT` column (all recurring jobs
--           are driven by the Schedules app instead)
--
-- The platform's app_platform/migrator.py invokes this with
-- search_path = app_jobs, public already set within its transaction.
-- The CREATE SCHEMA + SET search_path + BEGIN/COMMIT lines at the top
-- are a defensive belt-and-suspenders so this file also applies
-- cleanly if run by hand:
--     psql -d skipperbot -f apps/jobs/migrations/001_initial.sql
--
-- The whole migration runs in a single transaction so search_path
-- changes stick for every statement, and a failure rolls back cleanly.
--
-- Idempotent. Re-running is a no-op.

BEGIN;

CREATE SCHEMA IF NOT EXISTS app_jobs;
SET LOCAL search_path TO app_jobs, public;

-- =============================================================================
-- jobs — long-running background work
-- =============================================================================

CREATE TABLE IF NOT EXISTS jobs (
    id              text NOT NULL,
    name            text NOT NULL,
    job_type        text NOT NULL DEFAULT 'shell'::text,   -- CHECK relaxed in legacy 009
    command         text NOT NULL DEFAULT ''::text,
    description     text NOT NULL DEFAULT ''::text,
    scheduled_for   text NOT NULL DEFAULT ''::text,
    notify_user     text NOT NULL DEFAULT ''::text,
    status          text NOT NULL DEFAULT 'active'::text,
    created_by      text NOT NULL DEFAULT ''::text,
    created_at      timestamp with time zone NOT NULL DEFAULT now(),
    last_run_at     timestamp with time zone,
    last_result     text NOT NULL DEFAULT ''::text,
    run_count       integer NOT NULL DEFAULT 0,
    progress        text NOT NULL DEFAULT ''::text,
    cancelled       boolean NOT NULL DEFAULT false,
    config          jsonb NOT NULL DEFAULT '{}'::jsonb,
    output          jsonb NOT NULL DEFAULT '{}'::jsonb,

    -- Columns added in legacy migration 009
    progress_pct    integer NOT NULL DEFAULT 0,
    schedule_expr   jsonb NOT NULL DEFAULT '{}'::jsonb,
    started_at      timestamp with time zone,
    completed_at    timestamp with time zone,
    claimed_by      text NOT NULL DEFAULT ''::text,
    max_retries     integer NOT NULL DEFAULT 0,
    retry_count     integer NOT NULL DEFAULT 0,
    parent_job_id   text NOT NULL DEFAULT ''::text,
    error           text NOT NULL DEFAULT ''::text
);

DO $$ BEGIN
    ALTER TABLE jobs
        ADD CONSTRAINT jobs_pkey PRIMARY KEY (id);
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;

-- Only the `status` CHECK is preserved from the original schema.
-- Legacy migration 009 explicitly dropped the `job_type` CHECK so
-- handlers can register any string identifier.
DO $$ BEGIN
    ALTER TABLE jobs
        ADD CONSTRAINT jobs_status_check CHECK (status = ANY (ARRAY[
            'active'::text, 'paused'::text, 'completed'::text,
            'failed'::text, 'queued'::text, 'running'::text,
            'cancelled'::text
        ]));
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_jobs_status      ON jobs (status);
CREATE INDEX IF NOT EXISTS idx_jobs_type_status ON jobs (job_type, status);


-- =============================================================================
-- job_logs — per-job log lines (added in legacy migration 010)
-- =============================================================================
--
-- job_id is intentionally NOT a foreign key — the legacy schema
-- didn't have one either, and the partial-migration tolerance is
-- helpful (we can copy logs even if some source jobs were dropped
-- by hand on the legacy side).

CREATE TABLE IF NOT EXISTS job_logs (
    id          bigserial NOT NULL,
    job_id      text NOT NULL,
    created_at  timestamp with time zone NOT NULL DEFAULT now(),
    level       text NOT NULL DEFAULT 'INFO'::text,
    message     text NOT NULL DEFAULT ''::text
);

DO $$ BEGIN
    ALTER TABLE job_logs
        ADD CONSTRAINT job_logs_pkey PRIMARY KEY (id);
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_job_logs_job_id   ON job_logs (job_id);
CREATE INDEX IF NOT EXISTS idx_job_logs_job_time ON job_logs (job_id, created_at);

COMMIT;
