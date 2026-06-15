-- =============================================================================
-- Evolve — 004_run_activity.sql  (live mission-control observability)
-- =============================================================================
-- The gate_queue shows instances parked at a HUMAN gate. But the operator also wants to
-- watch the engine WORK — every in-flight instance (pre-Gate-1 included), who's active,
-- and a live scrolling log per agent. These two projections give the Evolve app that:
--
--   run       — one row per process-instance: the LIST view + current status/agent.
--   activity  — append-only event stream: the per-agent SCROLLING LOG.
--
-- Box 1 (the engine) is the only writer, via the service principal. Files-as-truth still
-- holds — this is a display projection, discardable and rebuildable. Idempotent.

BEGIN;

CREATE SCHEMA IF NOT EXISTS app_evolve;
SET LOCAL search_path TO app_evolve, public;

CREATE TABLE IF NOT EXISTS run (
    instance_id   TEXT PRIMARY KEY,
    title         TEXT NOT NULL DEFAULT '',
    source        TEXT NOT NULL DEFAULT '',     -- github#12 | manual:… | chat
    phase         TEXT NOT NULL DEFAULT '',     -- intake | spec | build | done
    status        TEXT NOT NULL DEFAULT 'running',  -- running | waiting | building | merged | rejected | error
    current_agent TEXT NOT NULL DEFAULT '',     -- who is active right now
    current_node  TEXT NOT NULL DEFAULT '',
    created_at    TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at    TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS run_active_idx ON run (updated_at DESC);

CREATE TABLE IF NOT EXISTS activity (
    id          BIGSERIAL PRIMARY KEY,
    instance_id TEXT NOT NULL,
    agent       TEXT NOT NULL DEFAULT '',       -- the agent/lane this line belongs to
    kind        TEXT NOT NULL DEFAULT 'info',   -- node | agent_start | tool | emit | agent_end | info | error
    message     TEXT NOT NULL DEFAULT '',
    ts          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS activity_instance_idx ON activity (instance_id, id);

COMMIT;
