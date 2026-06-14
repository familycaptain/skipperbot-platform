-- =============================================================================
-- Evolve — 003_gate_queue.sql
-- =============================================================================
-- The operator work queue: one row per process-instance parked at a HUMAN gate
-- (GATE 1 approve-intent / GATE 2 approve-result). The Evolve engine (box 1) pushes
-- the pre-digested review packet here when it blocks; the Evolve UI reads it, the
-- operator decides (approve/reject/change), and the engine resumes on that decision.
-- The full packet is kept as JSONB; a few columns are denormalised for the list view.
-- Idempotent.

BEGIN;

CREATE SCHEMA IF NOT EXISTS app_evolve;
SET LOCAL search_path TO app_evolve, public;

CREATE TABLE IF NOT EXISTS gate_queue (
    instance_id   TEXT PRIMARY KEY,
    gate          TEXT NOT NULL,                       -- gate1 | gate2
    title         TEXT NOT NULL DEFAULT '',            -- work-item title
    rec_action    TEXT NOT NULL DEFAULT '',            -- recommended action (approve/change/...)
    rec_why       TEXT NOT NULL DEFAULT '',
    packet        JSONB NOT NULL DEFAULT '{}'::jsonb,  -- full pipeline.packet() (+ diff)
    status        TEXT NOT NULL DEFAULT 'waiting',     -- waiting | decided
    decision      TEXT,                                -- approve | reject | change
    decided_by    TEXT,
    created_at    TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    decided_at    TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS gate_queue_status_idx ON gate_queue (status, created_at DESC);

COMMIT;
