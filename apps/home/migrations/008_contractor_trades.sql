-- Home App: Contractor Trades (configurable)
-- Replaces the hardcoded CONTRACTOR_TRADES list in HomeApp.jsx with a
-- household-configurable DB table, mirroring home_task_categories (004).
-- contractor.trade STAYS a free-form label (home_contractors.trade is unchanged);
-- this table only drives the Add/Edit picker + the Manage-trades screen.

SET LOCAL search_path TO app_home, public;

CREATE TABLE IF NOT EXISTS home_contractor_trades (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    sort_order  INT NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_home_contractor_trades_sort ON home_contractor_trades(sort_order, name);

-- Seed the common home-service trades (idempotent). Stable ids so re-running
-- the migration never duplicates a seed.
INSERT INTO home_contractor_trades (id, name, sort_order) VALUES
    ('hctr-general',    'General',           0),
    ('hctr-plumber',    'Plumber',           1),
    ('hctr-electrician','Electrician',       2),
    ('hctr-hvac',       'HVAC',              3),
    ('hctr-lawn',       'Lawn',              4),
    ('hctr-landscaping','Landscaping',       5),
    ('hctr-roofer',     'Roofer',            6),
    ('hctr-gutters',    'Gutters',           7),
    ('hctr-painter',    'Painter',           8),
    ('hctr-handyman',   'Handyman',          9),
    ('hctr-pest',       'Pest Control',      10),
    ('hctr-appliance',  'Appliance Repair',  11),
    ('hctr-cleaning',   'Cleaning',          12),
    ('hctr-flooring',   'Flooring',          13),
    ('hctr-garage',     'Garage Door',       14)
ON CONFLICT (id) DO NOTHING;
