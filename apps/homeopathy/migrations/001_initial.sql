-- Homeopathy app — initial migration
-- Creates tables in app_homeopathy schema and copies data from public.

-- ============================================================================
-- SOURCES (suppliers)
-- ============================================================================

CREATE TABLE IF NOT EXISTS homeo_sources (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    website         TEXT,
    phone           TEXT,
    notes           TEXT DEFAULT '',
    created_by      TEXT DEFAULT '',
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

-- ============================================================================
-- MEDICINES (name + description)
-- ============================================================================

CREATE TABLE IF NOT EXISTS homeo_medicines (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    description     TEXT DEFAULT '',
    notes           TEXT DEFAULT '',
    created_by      TEXT DEFAULT '',
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

-- ============================================================================
-- REMEDIES (medicine + strength)
-- ============================================================================

CREATE TABLE IF NOT EXISTS homeo_remedies (
    id              TEXT PRIMARY KEY,
    medicine_id     TEXT NOT NULL REFERENCES homeo_medicines(id) ON DELETE CASCADE,
    strength        TEXT NOT NULL,
    source_id       TEXT REFERENCES homeo_sources(id) ON DELETE SET NULL,
    notes           TEXT DEFAULT '',
    created_by      TEXT DEFAULT '',
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE(medicine_id, strength)
);

-- ============================================================================
-- BOTTLE SIZES
-- ============================================================================

CREATE TABLE IF NOT EXISTS homeo_bottle_sizes (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    notes           TEXT DEFAULT '',
    created_by      TEXT DEFAULT '',
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- ============================================================================
-- LOCATIONS
-- ============================================================================

CREATE TABLE IF NOT EXISTS homeo_locations (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    notes           TEXT DEFAULT '',
    created_by      TEXT DEFAULT '',
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- ============================================================================
-- BOTTLES (inventory)
-- ============================================================================

CREATE TABLE IF NOT EXISTS homeo_bottles (
    id              TEXT PRIMARY KEY,
    remedy_id       TEXT NOT NULL REFERENCES homeo_remedies(id) ON DELETE CASCADE,
    size_id         TEXT REFERENCES homeo_bottle_sizes(id) ON DELETE SET NULL,
    location_id     TEXT REFERENCES homeo_locations(id) ON DELETE SET NULL,
    fullness        INTEGER NOT NULL DEFAULT 100 CHECK (fullness BETWEEN 0 AND 100),
    last_checked    DATE,
    notes           TEXT DEFAULT '',
    created_by      TEXT DEFAULT '',
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_homeo_bottles_remedy   ON homeo_bottles(remedy_id);
CREATE INDEX IF NOT EXISTS idx_homeo_bottles_size     ON homeo_bottles(size_id);
CREATE INDEX IF NOT EXISTS idx_homeo_bottles_location ON homeo_bottles(location_id);
CREATE INDEX IF NOT EXISTS idx_homeo_bottles_low      ON homeo_bottles(fullness) WHERE fullness <= 25;