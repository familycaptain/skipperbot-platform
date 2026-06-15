-- =============================================================================
-- Evolve — 006_run_archived.sql
-- =============================================================================
-- Let the operator archive runs out of the default list (without deleting the record):
-- superseded duplicates, dead test runs, abandoned/stuck rows. The list shows non-archived
-- by default; an "archived" view shows them and allows unarchive. Idempotent.

BEGIN;

SET LOCAL search_path TO app_evolve, public;

ALTER TABLE run ADD COLUMN IF NOT EXISTS archived BOOLEAN NOT NULL DEFAULT false;
CREATE INDEX IF NOT EXISTS run_archived_idx ON run (archived, updated_at DESC);

COMMIT;
