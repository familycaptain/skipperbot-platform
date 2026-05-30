-- Newsletter App — Subscribers table + test_email config field

CREATE TABLE IF NOT EXISTS newsletter_subscribers (
    id          TEXT PRIMARY KEY,
    email       TEXT NOT NULL,
    name        TEXT NOT NULL DEFAULT '',
    level       TEXT NOT NULL DEFAULT 'free' CHECK (level IN ('free', 'paid')),
    active      BOOLEAN NOT NULL DEFAULT true,
    notes       TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(email)
);

CREATE INDEX IF NOT EXISTS idx_newsletter_subscribers_active
    ON newsletter_subscribers(active, level);

ALTER TABLE newsletter_config
    ADD COLUMN IF NOT EXISTS test_email TEXT NOT NULL DEFAULT '';
