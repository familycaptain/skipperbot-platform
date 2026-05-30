-- Locator app — initial migration
-- Creates locator tables in the app_locator schema.
-- (Migrator runs with search_path = app_locator, public, so unqualified
--  CREATE TABLE lands in app_locator.)

-- ============================================================================
-- ITEM LOCATIONS (predefined storage locations)
-- ============================================================================

CREATE TABLE IF NOT EXISTS item_locations (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    description     TEXT NOT NULL DEFAULT '',
    sort_order      INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================================
-- LOCATED ITEMS
-- ============================================================================

CREATE TABLE IF NOT EXISTS located_items (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    location        TEXT NOT NULL DEFAULT '',
    sub_location    TEXT NOT NULL DEFAULT '',
    category        TEXT NOT NULL DEFAULT '',
    tags            TEXT[] NOT NULL DEFAULT '{}',
    quantity        INTEGER,
    notes           TEXT NOT NULL DEFAULT '',
    created_by      TEXT NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_located_items_location ON located_items (location);
CREATE INDEX IF NOT EXISTS idx_located_items_category ON located_items (category);
CREATE INDEX IF NOT EXISTS idx_located_items_tags ON located_items USING GIN (tags);
CREATE INDEX IF NOT EXISTS idx_located_items_created_at ON located_items (created_at DESC);

-- ============================================================================
-- LOCATOR–IMAGE LINKS (soft FK to public.images — no cross-schema constraint)
-- ============================================================================

CREATE TABLE IF NOT EXISTS locator_images (
    item_id         TEXT NOT NULL REFERENCES located_items(id) ON DELETE CASCADE,
    image_id        TEXT NOT NULL,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (item_id, image_id)
);

CREATE INDEX IF NOT EXISTS idx_locator_images_item ON locator_images (item_id);
CREATE INDEX IF NOT EXISTS idx_locator_images_image ON locator_images (image_id);
