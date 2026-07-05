-- Home App — Contractors Tab
-- Household service-provider directory (records, not tasks)

SET LOCAL search_path TO app_home, public;

CREATE TABLE IF NOT EXISTS home_contractors (
    id              TEXT PRIMARY KEY,           -- hc-{hex8}
    name            TEXT NOT NULL,
    trade           TEXT NOT NULL DEFAULT 'General',   -- e.g. "Electrician", "Plumber"
    company         TEXT NOT NULL DEFAULT '',
    phone           TEXT NOT NULL DEFAULT '',
    email           TEXT NOT NULL DEFAULT '',
    rating          SMALLINT CHECK (rating IS NULL OR (rating BETWEEN 1 AND 5)),
    last_used       DATE,
    jobs_history    TEXT NOT NULL DEFAULT '',
    notes           TEXT NOT NULL DEFAULT '',
    created_by      TEXT NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_home_contractors_trade     ON home_contractors (trade);
CREATE INDEX IF NOT EXISTS idx_home_contractors_last_used ON home_contractors (last_used);
CREATE INDEX IF NOT EXISTS idx_home_contractors_created   ON home_contractors (created_at DESC);
