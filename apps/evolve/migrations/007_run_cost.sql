-- =============================================================================
-- Evolve — 007_run_cost.sql
-- =============================================================================
-- Per-run spend, so the operator sees a live running total at the top of the app
-- (sum across runs). The engine reports each run's cumulative cost from the ledger.
-- Idempotent.

BEGIN;

SET LOCAL search_path TO app_evolve, public;

ALTER TABLE run ADD COLUMN IF NOT EXISTS cost_usd REAL NOT NULL DEFAULT 0;

COMMIT;
