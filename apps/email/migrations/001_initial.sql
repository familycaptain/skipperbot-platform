-- Email App — Initial migration
-- Creates tables in app_email schema and copies data from public schema.
-- Note: search_path is set to app_email, public by the migrator.

-- ============================================================================
-- Accounts
-- ============================================================================

CREATE TABLE IF NOT EXISTS email_accounts (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,              -- soft ref to public.users(name)
    email_address   TEXT NOT NULL,
    display_name    TEXT DEFAULT '',
    credentials     JSONB NOT NULL DEFAULT '{}',
    scopes          TEXT[] DEFAULT '{}',
    active          BOOLEAN NOT NULL DEFAULT true,
    last_synced_at  TIMESTAMPTZ,
    history_id      TEXT DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================================
-- Rules
-- ============================================================================

CREATE TABLE IF NOT EXISTS email_rules (
    id              TEXT PRIMARY KEY,
    account_id      TEXT NOT NULL REFERENCES email_accounts(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    priority        INTEGER NOT NULL DEFAULT 100,
    active          BOOLEAN NOT NULL DEFAULT true,
    conditions      JSONB NOT NULL DEFAULT '{}',
    actions         JSONB NOT NULL DEFAULT '{}',
    stop_processing BOOLEAN NOT NULL DEFAULT true,
    match_count     INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ
);

-- ============================================================================
-- Processing Log
-- ============================================================================

CREATE TABLE IF NOT EXISTS email_log (
    id              TEXT PRIMARY KEY,
    account_id      TEXT NOT NULL REFERENCES email_accounts(id) ON DELETE CASCADE,
    gmail_msg_id    TEXT NOT NULL,
    thread_id       TEXT DEFAULT '',
    subject         TEXT DEFAULT '',
    sender          TEXT DEFAULT '',
    received_at     TIMESTAMPTZ,
    rule_id         TEXT,
    actions_taken   JSONB NOT NULL DEFAULT '[]',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_email_log_gmail_msg
    ON email_log (gmail_msg_id);
CREATE INDEX IF NOT EXISTS idx_email_log_account_date
    ON email_log (account_id, received_at DESC);
CREATE INDEX IF NOT EXISTS idx_email_rules_account_priority
    ON email_rules (account_id, priority);