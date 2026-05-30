-- Auto Maintenance app — initial migration
-- Creates tables in app_auto schema and copies data from public.

-- ============================================================================
-- VEHICLES
-- ============================================================================

CREATE TABLE IF NOT EXISTS vehicles (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    make            TEXT NOT NULL DEFAULT '',
    model           TEXT NOT NULL DEFAULT '',
    trim_level      TEXT NOT NULL DEFAULT '',
    year            INTEGER,
    color           TEXT NOT NULL DEFAULT '',
    vin             TEXT NOT NULL DEFAULT '',
    license_plate   TEXT NOT NULL DEFAULT '',
    odometer        INTEGER,
    notes           TEXT NOT NULL DEFAULT '',
    created_by      TEXT NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_vehicles_created_at ON vehicles (created_at DESC);

-- ============================================================================
-- SERVICE RECORDS
-- ============================================================================

CREATE TABLE IF NOT EXISTS service_records (
    id                  TEXT PRIMARY KEY,
    vehicle_id          TEXT NOT NULL REFERENCES vehicles(id) ON DELETE CASCADE,
    service_type        TEXT NOT NULL DEFAULT '',
    description         TEXT NOT NULL DEFAULT '',
    date_performed      DATE,
    odometer_at_service INTEGER,
    cost                NUMERIC(10,2),
    shop_name           TEXT NOT NULL DEFAULT '',
    next_due_date       DATE,
    next_due_mileage    INTEGER,
    reminder_id         TEXT,
    notes               TEXT NOT NULL DEFAULT '',
    created_by          TEXT NOT NULL DEFAULT '',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_service_records_vehicle ON service_records (vehicle_id);
CREATE INDEX IF NOT EXISTS idx_service_records_date ON service_records (date_performed DESC);
CREATE INDEX IF NOT EXISTS idx_service_records_type ON service_records (service_type);

-- ============================================================================
-- VEHICLE ISSUES
-- ============================================================================

CREATE TABLE IF NOT EXISTS vehicle_issues (
    id                  TEXT PRIMARY KEY,
    vehicle_id          TEXT NOT NULL REFERENCES vehicles(id) ON DELETE CASCADE,
    title               TEXT NOT NULL,
    description         TEXT NOT NULL DEFAULT '',
    severity            TEXT NOT NULL DEFAULT 'minor'
                        CHECK (severity IN ('minor', 'moderate', 'major', 'critical')),
    status              TEXT NOT NULL DEFAULT 'open'
                        CHECK (status IN ('open', 'monitoring', 'fixed')),
    date_noticed        DATE,
    date_fixed          DATE,
    fix_description     TEXT NOT NULL DEFAULT '',
    cost                NUMERIC(10,2),
    notes               TEXT NOT NULL DEFAULT '',
    created_by          TEXT NOT NULL DEFAULT '',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_vehicle_issues_vehicle ON vehicle_issues (vehicle_id);
CREATE INDEX IF NOT EXISTS idx_vehicle_issues_status ON vehicle_issues (status);

-- ============================================================================
-- VEHICLE VALUATIONS
-- ============================================================================

CREATE TABLE IF NOT EXISTS vehicle_valuations (
    id                      TEXT PRIMARY KEY,
    vehicle_id              TEXT NOT NULL REFERENCES vehicles(id) ON DELETE CASCADE,
    date_recorded           DATE NOT NULL,
    private_party_value     NUMERIC(10,2),
    trade_in_value          NUMERIC(10,2),
    condition               TEXT NOT NULL DEFAULT 'good'
                            CHECK (condition IN ('excellent', 'very_good', 'good', 'fair')),
    mileage_at_valuation    INTEGER,
    source                  TEXT NOT NULL DEFAULT 'kbb'
                            CHECK (source IN ('kbb', 'edmunds', 'nada', 'other')),
    notes                   TEXT NOT NULL DEFAULT '',
    created_by              TEXT NOT NULL DEFAULT '',
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_vehicle_valuations_vehicle ON vehicle_valuations (vehicle_id);
CREATE INDEX IF NOT EXISTS idx_vehicle_valuations_date ON vehicle_valuations (date_recorded DESC);

-- ============================================================================
-- VEHICLE CONDITION REPORTS
-- ============================================================================

CREATE TABLE IF NOT EXISTS vehicle_conditions (
    id                  TEXT PRIMARY KEY,
    vehicle_id          TEXT NOT NULL REFERENCES vehicles(id) ON DELETE CASCADE,
    date_recorded       DATE NOT NULL,
    mileage_at_report   INTEGER,
    brakes              TEXT NOT NULL DEFAULT 'good'
                        CHECK (brakes IN ('good', 'fair', 'worn', 'needs_replacement')),
    tires               TEXT NOT NULL DEFAULT 'good'
                        CHECK (tires IN ('good', 'fair', 'worn', 'needs_replacement')),
    tire_tread_depth    NUMERIC(4,1),
    oil_life_pct        INTEGER,
    battery             TEXT NOT NULL DEFAULT 'good'
                        CHECK (battery IN ('good', 'fair', 'weak', 'needs_replacement')),
    exterior            TEXT NOT NULL DEFAULT 'good'
                        CHECK (exterior IN ('excellent', 'good', 'fair', 'poor')),
    interior            TEXT NOT NULL DEFAULT 'good'
                        CHECK (interior IN ('excellent', 'good', 'fair', 'poor')),
    lights_signals      TEXT NOT NULL DEFAULT 'all_working'
                        CHECK (lights_signals IN ('all_working', 'issues')),
    fluids              TEXT NOT NULL DEFAULT 'all_good'
                        CHECK (fluids IN ('all_good', 'needs_attention')),
    notes               TEXT NOT NULL DEFAULT '',
    created_by          TEXT NOT NULL DEFAULT '',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_vehicle_conditions_vehicle ON vehicle_conditions (vehicle_id);
CREATE INDEX IF NOT EXISTS idx_vehicle_conditions_date ON vehicle_conditions (date_recorded DESC);

-- ============================================================================
-- VEHICLE IMAGES (soft FK to public.images — no cross-schema constraint)
-- ============================================================================

CREATE TABLE IF NOT EXISTS vehicle_images (
    image_id            TEXT NOT NULL,
    vehicle_id          TEXT REFERENCES vehicles(id) ON DELETE CASCADE,
    issue_id            TEXT REFERENCES vehicle_issues(id) ON DELETE CASCADE,
    condition_id        TEXT REFERENCES vehicle_conditions(id) ON DELETE CASCADE,
    sort_order          INTEGER NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (image_id),
    CHECK (
        (vehicle_id IS NOT NULL AND issue_id IS NULL AND condition_id IS NULL) OR
        (vehicle_id IS NULL AND issue_id IS NOT NULL AND condition_id IS NULL) OR
        (vehicle_id IS NULL AND issue_id IS NULL AND condition_id IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_vehicle_images_vehicle ON vehicle_images (vehicle_id) WHERE vehicle_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_vehicle_images_issue ON vehicle_images (issue_id) WHERE issue_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_vehicle_images_condition ON vehicle_images (condition_id) WHERE condition_id IS NOT NULL;