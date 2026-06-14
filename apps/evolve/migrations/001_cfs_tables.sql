-- Evolve App — C/F/S projection (EVOLVE.md §4).
-- Files under specs/evolve/** are the source of truth; this table is the queryable
-- projection rebuilt by boot-sync (apps/evolve/store.py). Runs with
-- search_path = app_evolve, public. App migrations ship their own transaction.
BEGIN;

CREATE TABLE IF NOT EXISTS cfs_records (
    id          TEXT PRIMARY KEY,                 -- dotted id, e.g. evolve.cfs-store.boot-sync
    kind        TEXT NOT NULL,                    -- capability | feature | specification
    parent_id   TEXT,                             -- id minus last segment (NULL for capability)
    title       TEXT NOT NULL DEFAULT '',
    state       TEXT NOT NULL DEFAULT 'proposed', -- proposed..live..deprecated (§4)
    behavior    TEXT NOT NULL DEFAULT '',
    checksum    TEXT NOT NULL DEFAULT '',         -- content checksum for drift tracking
    path        TEXT NOT NULL DEFAULT '',         -- source file (organizational)
    raw         JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_cfs_kind   ON cfs_records(kind);
CREATE INDEX IF NOT EXISTS idx_cfs_parent ON cfs_records(parent_id);
CREATE INDEX IF NOT EXISTS idx_cfs_state  ON cfs_records(state);

COMMIT;
