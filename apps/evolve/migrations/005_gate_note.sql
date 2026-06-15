-- =============================================================================
-- Evolve — 005_gate_note.sql
-- =============================================================================
-- The operator's written response at a gate (answers to the design's "decisions for
-- you" + any free-text guidance). On a 'change' decision the engine feeds this back to
-- the spec team as human_note, so the agents revise WITH the operator's answers instead
-- of guessing again. Idempotent.

BEGIN;

SET LOCAL search_path TO app_evolve, public;

ALTER TABLE gate_queue ADD COLUMN IF NOT EXISTS note TEXT;

COMMIT;
