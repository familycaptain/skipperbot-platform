-- Bounties App — Initial migration
-- All tables in app_bounties schema (created automatically by app loader)

-- ============================================================================
-- BOUNTY TEMPLATES (recurring bounty definitions)
-- ============================================================================

CREATE TABLE IF NOT EXISTS bounty_templates (
    id              TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    value_cents     INTEGER NOT NULL,
    created_by      TEXT NOT NULL DEFAULT '',
    category        TEXT NOT NULL DEFAULT '',
    recurrence_days INTEGER NOT NULL,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_bounty_templates_active ON bounty_templates (is_active);

-- ============================================================================
-- BOUNTIES (individual instances)
-- ============================================================================

CREATE TABLE IF NOT EXISTS bounties (
    id              TEXT PRIMARY KEY,
    template_id     TEXT REFERENCES bounty_templates(id) ON DELETE SET NULL,
    title           TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    value_cents     INTEGER NOT NULL,
    category        TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'open'
                    CHECK (status IN ('open', 'submitted', 'approved', 'rejected', 'expired', 'cancelled')),
    created_by      TEXT NOT NULL DEFAULT '',
    submitted_by    TEXT,
    submitted_at    TIMESTAMPTZ,
    submission_note TEXT,
    reviewed_by     TEXT,
    reviewed_at     TIMESTAMPTZ,
    review_note     TEXT,
    expires_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_bounties_status ON bounties (status);
CREATE INDEX IF NOT EXISTS idx_bounties_template ON bounties (template_id);
CREATE INDEX IF NOT EXISTS idx_bounties_submitted_by ON bounties (submitted_by);
CREATE INDEX IF NOT EXISTS idx_bounties_category ON bounties (category);
CREATE INDEX IF NOT EXISTS idx_bounties_created_at ON bounties (created_at DESC);

-- ============================================================================
-- BOUNTY BALANCES (current balance per member)
-- ============================================================================

CREATE TABLE IF NOT EXISTS bounty_balances (
    user_id                 TEXT PRIMARY KEY,
    balance_cents           INTEGER NOT NULL DEFAULT 0,
    lifetime_earned_cents   INTEGER NOT NULL DEFAULT 0,
    lifetime_paid_out_cents INTEGER NOT NULL DEFAULT 0,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================================
-- BOUNTY TRANSACTIONS (immutable ledger)
-- ============================================================================

CREATE TABLE IF NOT EXISTS bounty_transactions (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    type            TEXT NOT NULL CHECK (type IN ('credit', 'debit_payment', 'adjustment')),
    amount_cents    INTEGER NOT NULL,
    balance_after_cents INTEGER NOT NULL,
    bounty_id       TEXT,
    payment_method  TEXT,
    note            TEXT,
    created_by      TEXT NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_bounty_transactions_user ON bounty_transactions (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_bounty_transactions_type ON bounty_transactions (type);
CREATE INDEX IF NOT EXISTS idx_bounty_transactions_bounty ON bounty_transactions (bounty_id);

-- ============================================================================
-- BOUNTY CONFIG (singleton settings)
-- ============================================================================

CREATE TABLE IF NOT EXISTS bounty_config (
    id               INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    min_payout_cents INTEGER NOT NULL DEFAULT 2000,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO bounty_config (id) VALUES (1) ON CONFLICT DO NOTHING;

-- ============================================================================
-- BOUNTY CATEGORIES (managed lookup)
-- ============================================================================

CREATE TABLE IF NOT EXISTS bounty_categories (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    icon        TEXT NOT NULL DEFAULT '',
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Seed default categories
INSERT INTO bounty_categories (id, name, icon, sort_order) VALUES
    ('bcat-yard0001', 'Yard',      '🌿', 0),
    ('bcat-kitc0001', 'Kitchen',   '🍽️', 1),
    ('bcat-bath0001', 'Bathroom',  '🚿', 2),
    ('bcat-bedr0001', 'Bedroom',   '🛏️', 3),
    ('bcat-gene0001', 'General',   '🏠', 4),
    ('bcat-laun0001', 'Laundry',   '👕', 5),
    ('bcat-pets0001', 'Pets',      '🐾', 6),
    ('bcat-tras0001', 'Trash',     '🗑️', 7)
ON CONFLICT (name) DO NOTHING;

-- ============================================================================
-- ENTITY TYPES
-- ============================================================================

INSERT INTO public.entity_types (prefix, name, id_format, table_name) VALUES
    ('bt',   'Bounty Template',    'bt-',   'app_bounties.bounty_templates'),
    ('bnt',  'Bounty',             'bnt-',  'app_bounties.bounties'),
    ('btx',  'Bounty Transaction', 'btx-',  'app_bounties.bounty_transactions'),
    ('bcat', 'Bounty Category',    'bcat-', 'app_bounties.bounty_categories')
ON CONFLICT (prefix) DO NOTHING;
