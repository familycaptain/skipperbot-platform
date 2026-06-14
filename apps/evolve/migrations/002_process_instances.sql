-- Evolve App — process-instances (EVOLVE.md §7; spec evolve.process-engine.instance-state).
-- One row per work-item walking the SDLC graph. The full instance (tokens, join
-- arrivals, context, transition log) is serialized in `doc` so it is durable +
-- resumable across a restart of either box. Runs with search_path = app_evolve, public.
BEGIN;

CREATE TABLE IF NOT EXISTS process_instances (
    id          TEXT PRIMARY KEY,                 -- pi-<hex8>
    model_id    TEXT NOT NULL,                    -- e.g. evolve-sdlc
    status      TEXT NOT NULL DEFAULT 'running',  -- running | blocked | done | rejected | parked
    doc         JSONB NOT NULL,                   -- serialized Instance (Instance.to_dict)
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_pi_status   ON process_instances(status);
CREATE INDEX IF NOT EXISTS idx_pi_model    ON process_instances(model_id);

COMMIT;
